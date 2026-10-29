import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/endpoints'
import type {
  ConfirmItemInput,
  ConfirmResult,
  ImportCandidate,
  StatementImport,
} from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { useDataVersion } from '../components/DataVersion'
import { useI18n } from '../i18n'
import { errorCode, importMessage, skipReason } from '../lib/importErrors'
import { formatMoney, fromCents, isValidAmount, monthlyCents } from '../lib/money'
import { readStored, removeStored, writeStored } from '../lib/storage'

const IMPORT_KEY = 'subtracker.import'
const MAX_BYTES = 2 * 1024 * 1024
const SLOW_AFTER_MS = 3000

type Stage = 'source' | 'parsing' | 'confirm' | 'done'
type Action = 'skip' | 'create' | 'update'

interface Choice {
  selected: boolean
  action: Action
  amount: string
}

type Choices = Record<string, Choice>

function initialChoices(data: StatementImport): Choices {
  const all = [...data.candidates, ...data.candidatesReview]
  return Object.fromEntries(
    all.map((item) => [
      item.candidateId,
      {
        selected: item.preselectRecommended,
        // A candidate that matches an existing subscription has a real choice,
        // so nothing is picked for the owner (contract, decision Р2).
        action: item.duplicateMatch === 'none' ? 'create' : 'skip',
        amount: item.amount,
      } satisfies Choice,
    ]),
  )
}

/** The three groups of the confirmation screen, derived from contract fields only. */
function groupsOf(data: StatementImport) {
  const main = data.candidates.filter((item) => item.duplicateMatch === 'none')
  const maybe = data.candidatesReview.filter((item) => item.duplicateMatch === 'none')
  const duplicates = [...data.candidates, ...data.candidatesReview].filter(
    (item) => item.duplicateMatch !== 'none',
  )
  return { main, maybe, duplicates }
}

function compositionOf(items: ConfirmItemInput[]): string {
  return JSON.stringify([...items].sort((a, b) => a.candidateId.localeCompare(b.candidateId)))
}

export default function Import() {
  const { t } = useI18n()
  const { user } = useAuth()
  const { bump } = useDataVersion()
  const navigate = useNavigate()
  const currency = user?.defaultCurrency ?? 'USD'

  const [stage, setStage] = useState<Stage>('source')
  const [file, setFile] = useState<File | null>(null)
  const [data, setData] = useState<StatementImport | null>(null)
  const [choices, setChoices] = useState<Choices>({})
  const [result, setResult] = useState<ConfirmResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [slow, setSlow] = useState(false)
  const [busy, setBusy] = useState(false)
  const [undoNote, setUndoNote] = useState<string | null>(null)

  // One key per composition: the same retry reuses it, any edit replaces it.
  const key = useRef<{ composition: string; value: string } | null>(null)

  const open = useCallback((imported: StatementImport) => {
    setData(imported)
    setChoices(initialChoices(imported))
    setStage('confirm')
    writeStored(IMPORT_KEY, imported.importId)
  }, [])

  // After a page reload the candidate list is restored from the server by id.
  useEffect(() => {
    const stored = readStored(IMPORT_KEY)
    if (!stored) return
    let cancelled = false
    api
      .readStatementImport(stored)
      .then((imported) => {
        if (!cancelled) open(imported)
      })
      .catch(() => removeStored(IMPORT_KEY))
    return () => {
      cancelled = true
    }
  }, [open])

  function pickFile(next: File | null) {
    setError(null)
    if (!next) return setFile(null)
    if (!/\.(csv|tsv|txt)$/i.test(next.name)) return setError(t.import.errors.wrongFormat)
    if (next.size === 0) return setError(t.import.errors.emptyFile)
    if (next.size > MAX_BYTES) return setError(t.import.errors.tooLarge)
    setFile(next)
  }

  async function parse() {
    if (!file) return
    setStage('parsing')
    setError(null)
    setSlow(false)
    const timer = setTimeout(() => setSlow(true), SLOW_AFTER_MS)
    try {
      open(await api.uploadStatement(file))
    } catch (failure) {
      setError(importMessage(failure, t))
      setStage('source')
    } finally {
      clearTimeout(timer)
    }
  }

  function itemsFor(): ConfirmItemInput[] {
    if (!data) return []
    const all = [...data.candidates, ...data.candidatesReview]
    return all.flatMap((candidate): ConfirmItemInput[] => {
      const choice = choices[candidate.candidateId]
      if (!choice || !choice.selected || choice.action === 'skip') return []
      if (choice.action === 'update') {
        return [
          {
            candidateId: candidate.candidateId,
            action: 'update' as const,
            targetSubscriptionId: candidate.matchedSubscription?.id,
            expectedAmount: candidate.matchedSubscription?.amount,
            amount: choice.amount,
          },
        ]
      }
      return [
        {
          candidateId: candidate.candidateId,
          ...(candidate.duplicateMatch === 'none' ? {} : { action: 'create' as const }),
          ...(choice.amount === candidate.amount ? {} : { amount: choice.amount }),
        },
      ]
    })
  }

  async function confirm() {
    if (!data) return
    const items = itemsFor()
    if (items.length === 0) return
    const composition = compositionOf(items)
    if (key.current?.composition !== composition) {
      key.current = { composition, value: crypto.randomUUID() }
    }
    setBusy(true)
    setError(null)
    try {
      const confirmed = await api.confirmStatementImport(
        data.importId,
        key.current.value,
        items,
      )
      setResult(confirmed)
      setStage('done')
      removeStored(IMPORT_KEY)
      bump()
    } catch (failure) {
      setError(importMessage(failure, t))
      if (errorCode(failure) === 'import.expired') setStage('source')
    } finally {
      setBusy(false)
    }
  }

  async function undo() {
    if (!result) return
    setBusy(true)
    let done = 0
    let kept = 0
    for (const created of result.created) {
      try {
        await api.deleteSubscription(created.subscriptionId)
        done += 1
      } catch {
        kept += 1
      }
    }
    for (const changed of result.updated) {
      try {
        await api.updateSubscription(changed.subscriptionId, {
          amount: changed.previous.amount,
        })
        done += 1
      } catch {
        kept += 1
      }
    }
    setUndoNote(kept > 0 ? t.import.undoPartial : t.import.undone(done))
    setResult({ ...result, created: [], updated: [] })
    setBusy(false)
    bump()
  }

  async function startOver() {
    if (data && stage === 'confirm') {
      await api.discardStatementImport(data.importId).catch(() => undefined)
    }
    removeStored(IMPORT_KEY)
    key.current = null
    setData(null)
    setResult(null)
    setFile(null)
    setError(null)
    setStage('source')
  }

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-6">
      <h1 className="text-2xl font-medium">{t.import.title}</h1>
      {error && (
        <p role="alert" className="mt-4 rounded-2xl border border-line p-4 text-sm">
          {error}
        </p>
      )}

      {stage === 'source' && (
        <SourceStep
          file={file}
          onPick={pickFile}
          onParse={parse}
          disabled={stage !== 'source'}
        />
      )}

      {stage === 'parsing' && (
        <p className="mt-6 text-muted" aria-live="polite">
          {t.import.parsing}
          {slow ? ` ${t.import.slow}` : ''}
        </p>
      )}

      {stage === 'confirm' && data && (
        <ConfirmStep
          data={data}
          choices={choices}
          setChoices={setChoices}
          currency={currency}
          busy={busy}
          onConfirm={confirm}
          onStartOver={startOver}
        />
      )}

      {stage === 'done' && result && (
        <DoneStep
          result={result}
          currency={currency}
          busy={busy}
          undoNote={undoNote}
          onUndo={undo}
          onGoToList={() => navigate('/subscriptions')}
        />
      )}
    </div>
  )
}

// --- Steps -----------------------------------------------------------------

function SourceStep({
  file,
  onPick,
  onParse,
  disabled,
}: {
  file: File | null
  onPick: (file: File | null) => void
  onParse: () => void
  disabled: boolean
}) {
  const { t } = useI18n()
  const input = useRef<HTMLInputElement>(null)

  return (
    <section className="mt-6 space-y-4">
      <p className="text-muted">{t.import.lead}</p>
      <div
        className="rounded-3xl border border-dashed border-line p-8 text-center"
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault()
          onPick(event.dataTransfer.files[0] ?? null)
        }}
      >
        <p className="text-muted">{t.import.drop}</p>
        <input
          ref={input}
          type="file"
          accept=".csv,.tsv,.txt,text/csv"
          className="sr-only"
          aria-label={t.import.choose}
          onChange={(event) => onPick(event.target.files?.[0] ?? null)}
        />
        <button
          type="button"
          className="mt-4 rounded-full bg-text px-5 py-2 text-bg"
          onClick={() => input.current?.click()}
        >
          {t.import.choose}
        </button>
        <p className="mt-4 text-xs text-muted">{t.import.limits}</p>
      </div>
      {file && (
        <div className="flex items-center justify-between rounded-2xl border border-line p-4">
          <span className="text-sm">{file.name}</span>
          <div className="flex gap-2">
            <button type="button" className="text-sm text-muted" onClick={() => onPick(null)}>
              {t.import.remove}
            </button>
            <button
              type="button"
              className="rounded-full bg-text px-5 py-2 text-sm text-bg"
              disabled={disabled && false}
              onClick={onParse}
            >
              {t.import.parse}
            </button>
          </div>
        </div>
      )}
    </section>
  )
}

function Group({
  title,
  items,
  open,
  children,
}: {
  title: string
  items: ImportCandidate[]
  open: boolean
  children: (item: ImportCandidate) => React.ReactNode
}) {
  const [expanded, setExpanded] = useState(open)
  if (items.length === 0) return null
  return (
    <section className="mt-6">
      <button
        type="button"
        className="flex w-full items-center justify-between text-left text-sm font-medium"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
      >
        <span>
          {title} · {items.length}
        </span>
      </button>
      {expanded && <ul className="mt-3 space-y-3">{items.map((item) => children(item))}</ul>}
    </section>
  )
}

function ConfirmStep({
  data,
  choices,
  setChoices,
  currency,
  busy,
  onConfirm,
  onStartOver,
}: {
  data: StatementImport
  choices: Choices
  setChoices: React.Dispatch<React.SetStateAction<Choices>>
  currency: string
  busy: boolean
  onConfirm: () => void
  onStartOver: () => void
}) {
  const { t } = useI18n()
  const { main, maybe, duplicates } = groupsOf(data)
  const all = [...data.candidates, ...data.candidatesReview]

  const FALLBACK: Choice = { selected: false, action: 'skip', amount: '0.00' }
  const choiceOf = (id: string): Choice => choices[id] ?? FALLBACK
  const set = (id: string, patch: Partial<Choice>) =>
    setChoices((previous) => ({ ...previous, [id]: { ...choiceOf(id), ...patch } }))

  const chosen = all.filter((item) => choiceOf(item.candidateId).selected)
  const needsAction = chosen.filter(
    (item) => item.duplicateMatch !== 'none' && choiceOf(item.candidateId).action === 'skip',
  )
  const totalCents = chosen.reduce((sum, item) => {
    const choice = choiceOf(item.candidateId)
    if (choice.action === 'update') return sum
    return sum + monthlyCents(choice.amount, item.billingCycle, item.customIntervalDays)
  }, 0)

  const row = (item: ImportCandidate) => {
    const choice = choiceOf(item.candidateId)
    const matched = item.matchedSubscription
    return (
      <li key={item.candidateId} className="rounded-2xl border border-line p-4">
        <label className="flex items-start gap-3">
          <input
            type="checkbox"
            checked={choice.selected}
            aria-label={item.name}
            onChange={(event) => set(item.candidateId, { selected: event.target.checked })}
          />
          <span className="flex-1">
            <span className="flex flex-wrap items-baseline gap-2">
              <span className="font-medium">{item.name}</span>
              <span className="text-xs text-muted">{t.import.level[item.confidenceLabel]}</span>
              {matched && (
                <span className="rounded-full border border-line px-2 py-0.5 text-xs">
                  {t.import.duplicateBadge}
                </span>
              )}
            </span>
            <span className="mt-1 block text-sm text-muted">
              {formatMoney(choice.amount, currency)} · {t.import.charges(item.occurrenceCount)}
              {item.cycleBasis === 'text' && ` · ${t.import.basisText}`}
              {item.cycleBasis === 'single_interval' && ` · ${t.import.basisSingle}`}
            </span>
            {item.previousAmount && (
              <span className="mt-1 block text-xs text-muted">
                {t.import.priceChanged(
                  formatMoney(item.previousAmount, currency),
                  formatMoney(item.amount, currency),
                )}
              </span>
            )}
            {matched && (
              <span className="mt-1 block text-xs text-muted">
                {t.import.yoursIs(formatMoney(matched.amount, currency))}{' '}
                {formatMoney(item.amount, currency)}
              </span>
            )}
          </span>
        </label>

        <details className="mt-2">
          <summary className="cursor-pointer text-xs text-muted">
            {t.import.charges(item.occurrenceCount)}
          </summary>
          <ul className="mt-2 space-y-1 text-xs text-muted">
            {item.occurrences.map((occurrence) => (
              <li key={occurrence.line}>
                {occurrence.date} · {formatMoney(occurrence.amount, currency)} ·{' '}
                {occurrence.rawDescription}
              </li>
            ))}
          </ul>
        </details>

        {choice.selected && (
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <label className="text-xs text-muted">
              <input
                className="ml-2 w-28 rounded-lg border border-line bg-transparent px-2 py-1"
                value={choice.amount}
                aria-label={`${item.name} amount`}
                onChange={(event) => set(item.candidateId, { amount: event.target.value })}
              />
            </label>
            {!isValidAmount(choice.amount) && (
              <span className="text-xs text-danger">{t.form.errAmount}</span>
            )}
          </div>
        )}

        {matched && choice.selected && (
          <fieldset className="mt-3 flex flex-wrap gap-3 text-xs">
            <legend className="sr-only">{item.name}</legend>
            {(['skip', 'create', ...(item.duplicateMatch === 'amount_differs' ? ['update'] : [])] as Action[]).map(
              (action) => (
                <label key={action} className="flex items-center gap-1">
                  <input
                    type="radio"
                    name={`action-${item.candidateId}`}
                    checked={choice.action === action}
                    onChange={() => set(item.candidateId, { action })}
                  />
                  {action === 'skip' && t.import.actionSkip}
                  {action === 'create' && t.import.actionCreate}
                  {action === 'update' && t.import.actionUpdate(formatMoney(item.amount, currency))}
                </label>
              ),
            )}
            {choice.action === 'skip' && (
              <span className="text-danger">{t.import.actionRequired}</span>
            )}
            {choice.action === 'create' && (
              <span className="text-muted">{t.import.willCreateSecond}</span>
            )}
          </fieldset>
        )}
      </li>
    )
  }

  return (
    <section className="mt-6">
      {data.statement.incompleteData && (
        <p className="rounded-2xl border border-line p-4 text-sm">
          {t.import.unparsed(data.statement.rowsSkipped, data.statement.rowsTotal)} ·{' '}
          {t.import.incomplete}
        </p>
      )}

      {all.length === 0 && (
        <p className="mt-6 rounded-2xl border border-line p-6">
          <strong>{t.import.empty}</strong>
          <span className="mt-1 block text-sm text-muted">{t.import.emptyBody}</span>
        </p>
      )}
      {all.length > 0 && main.length === 0 && duplicates.length > 0 && maybe.length === 0 && (
        <p className="mt-6 text-sm text-muted">{t.import.allDuplicates}</p>
      )}

      <div className="mt-4 flex flex-wrap gap-3 text-sm">
        <button
          type="button"
          className="rounded-full border border-line px-4 py-1"
          onClick={() =>
            setChoices((previous) => {
              const next = { ...previous }
              for (const item of main) {
                next[item.candidateId] = { ...choiceOf(item.candidateId), selected: true }
              }
              return next
            })
          }
        >
          {t.import.selectAll}
        </button>
        <button
          type="button"
          className="rounded-full border border-line px-4 py-1"
          onClick={() =>
            setChoices((previous) =>
              Object.fromEntries(
                Object.entries(previous).map(([id, choice]) => [id, { ...choice, selected: false }]),
              ),
            )
          }
        >
          {t.import.clearAll}
        </button>
        <span className="text-muted">{t.import.groupsExcluded}</span>
      </div>

      <Group title={t.import.found} items={main} open>
        {row}
      </Group>
      <Group title={t.import.maybe} items={maybe} open={false}>
        {row}
      </Group>
      <Group title={t.import.duplicates} items={duplicates} open={false}>
        {row}
      </Group>

      <div className="sticky bottom-0 mt-8 flex flex-wrap items-center gap-4 border-t border-line bg-bg py-4">
        <span className="text-sm">
          {t.import.selected(chosen.length, all.length)} ·{' '}
          {t.import.monthly(formatMoney(fromCents(totalCents), currency))}
        </span>
        <button
          type="button"
          className="rounded-full bg-text px-5 py-2 text-sm text-bg disabled:opacity-50"
          disabled={busy || chosen.length === 0 || needsAction.length > 0}
          onClick={onConfirm}
        >
          {busy ? t.import.saving : t.import.confirm}
        </button>
        {chosen.length === 0 && <span className="text-sm text-muted">{t.import.nothingSelected}</span>}
        <button type="button" className="text-sm text-muted" onClick={onStartOver}>
          {t.import.errors.startOver}
        </button>
      </div>
    </section>
  )
}

function DoneStep({
  result,
  currency,
  busy,
  undoNote,
  onUndo,
  onGoToList,
}: {
  result: ConfirmResult
  currency: string
  busy: boolean
  undoNote: string | null
  onUndo: () => void
  onGoToList: () => void
}) {
  const { t } = useI18n()
  const totalCents = result.created.reduce(
    (sum, item) => sum + monthlyCents(item.amount, item.billingCycle, null),
    0,
  )

  return (
    <section className="mt-6 space-y-4" aria-live="polite">
      <h2 className="text-lg font-medium">{t.import.doneTitle(result.created.length)}</h2>
      {result.created.length > 0 && (
        <>
          <p className="text-muted">{t.import.doneMonthly(formatMoney(fromCents(totalCents), currency))}</p>
          <ul className="space-y-1 text-sm">
            {result.created.map((item) => (
              <li key={item.candidateId}>
                {item.name} · {formatMoney(item.amount, currency)}
              </li>
            ))}
          </ul>
        </>
      )}

      {result.updated.length > 0 && (
        <>
          <h3 className="text-sm font-medium">{t.import.doneUpdated(result.updated.length)}</h3>
          <ul className="space-y-1 text-sm">
            {result.updated.map((item) => (
              <li key={item.candidateId}>
                {item.name}:{' '}
                {t.import.priceChanged(
                  formatMoney(item.previous.amount, currency),
                  formatMoney(item.current.amount, currency),
                )}
              </li>
            ))}
          </ul>
        </>
      )}

      {/* Elements the server did not apply: a normal outcome, not a failure. */}
      {result.skipped.length > 0 && (
        <div className="rounded-2xl border border-line p-4">
          <h3 className="text-sm font-medium">{t.import.notApplied(result.skipped.length)}</h3>
          <ul className="mt-2 space-y-1 text-sm text-muted">
            {result.skipped.map((item) => (
              <li key={item.candidateId}>{skipReason(item.code, t)}</li>
            ))}
          </ul>
        </div>
      )}

      {undoNote && <p className="text-sm text-muted">{undoNote}</p>}

      <div className="flex flex-wrap gap-3">
        <button type="button" className="rounded-full bg-text px-5 py-2 text-sm text-bg" onClick={onGoToList}>
          {t.import.toSubscriptions}
        </button>
        {(result.created.length > 0 || result.updated.length > 0) && (
          <button type="button" className="text-sm text-muted" disabled={busy} onClick={onUndo}>
            {busy ? t.import.undoing : t.import.undo}
          </button>
        )}
      </div>
    </section>
  )
}

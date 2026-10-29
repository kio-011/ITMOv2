import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setTokens } from '../api/session'
import { createState, installMockApi, type MockState } from '../test/mockApi'
import { importBody } from '../test/importFixtures'
import { renderApp } from '../test/renderApp'

let state: MockState

beforeEach(() => {
  localStorage.clear()
  state = createState({ importResponse: { status: 201, body: importBody() } })
  installMockApi(state)
  setTokens({ accessToken: 'a', refreshToken: 'r' })
})

const file = (name = 'statement.csv', size = 1024) => {
  const blob = new File(['date,description,amount,currency\n'], name, { type: 'text/csv' })
  Object.defineProperty(blob, 'size', { value: size })
  return blob
}

async function uploadFixture(user: ReturnType<typeof userEvent.setup>) {
  renderApp('/import')
  await user.upload(await screen.findByLabelText('Выбрать файл'), file())
  await user.click(screen.getByRole('button', { name: 'Найти подписки' }))
  return screen.findByRole('checkbox', { name: 'Claude.ai' })
}

describe('statement import', () => {
  it('shows the three groups and preselects only the confident finds', async () => {
    const user = userEvent.setup()
    await uploadFixture(user)

    expect(screen.getByRole('checkbox', { name: 'Claude.ai' })).toBeChecked()
    expect(screen.getByText(/Возможно, подписки · 1/)).toBeInTheDocument()
    expect(screen.getByText(/Уже есть у вас · 1/)).toBeInTheDocument()

    // Groups that need a decision are collapsed, and nothing in them is preselected.
    expect(screen.queryByRole('checkbox', { name: 'Netflix' })).not.toBeInTheDocument()
    await user.click(screen.getByText(/Уже есть у вас · 1/))
    expect(screen.getByRole('checkbox', { name: 'Netflix' })).not.toBeChecked()
  })

  it('warns that part of the statement could not be read', async () => {
    const user = userEvent.setup()
    await uploadFixture(user)
    expect(screen.getByText(/1 из 38 строк не разобрано/)).toBeInTheDocument()
  })

  it('refuses a file over the limit before sending it', async () => {
    const user = userEvent.setup()
    renderApp('/import')
    await user.upload(await screen.findByLabelText('Выбрать файл'), file('big.csv', 3 * 1024 * 1024))

    expect(await screen.findByRole('alert')).toHaveTextContent(/больше 2 МиБ/)
    expect(state.calls.some((call) => call.path.startsWith('/api/imports'))).toBe(false)
  })

  it('refuses a file of the wrong type before sending it', async () => {
    const user = userEvent.setup()
    renderApp('/import')
    await user.upload(await screen.findByLabelText('Выбрать файл'), file('statement.pdf'))
    expect(await screen.findByRole('alert')).toHaveTextContent(/CSV/)
  })

  it('sends no action for a plain candidate and the chosen action for a duplicate', async () => {
    const user = userEvent.setup()
    await uploadFixture(user)
    state.confirmResponse = {
      status: 201,
      body: {
        import_id: 'imp_1',
        status: 'confirmed',
        created: [
          { candidate_id: 'cnd_1', subscription_id: 10, name: 'Claude.ai', amount: '20.00', billing_cycle: 'monthly', start_date: '2026-07-05', next_billing_date: '2026-11-05', created_despite_duplicate: false },
        ],
        updated: [
          { candidate_id: 'cnd_netflix', subscription_id: 2, name: 'Netflix', previous: { amount: '15.49' }, current: { amount: '17.99' } },
        ],
        skipped: [],
        created_count: 1,
        updated_count: 1,
        skipped_count: 0,
      },
    }

    await user.click(screen.getByText(/Уже есть у вас · 1/))
    const duplicate = screen.getByRole('checkbox', { name: 'Netflix' })
    await user.click(duplicate)
    await user.click(screen.getByRole('radio', { name: /Обновить мою подписку/ }))
    await user.click(screen.getByRole('button', { name: 'Добавить выбранные' }))

    await screen.findByText(/Добавлено подписок: 1/)
    const confirm = state.calls.find((call) => call.path.endsWith('/confirm'))!
    const items = (confirm.body as { items: Record<string, unknown>[] }).items
    expect(items.find((item) => item.candidate_id === 'cnd_1')).not.toHaveProperty('action')
    expect(items.find((item) => item.candidate_id === 'cnd_netflix')).toMatchObject({
      action: 'update',
      target_subscription_id: 2,
      expected_amount: '15.49',
    })
    expect(confirm.body).toHaveProperty('idempotency_key')
  })

  it('blocks confirmation while a selected duplicate has no action', async () => {
    const user = userEvent.setup()
    await uploadFixture(user)
    await user.click(screen.getByText(/Уже есть у вас · 1/))
    await user.click(screen.getByRole('checkbox', { name: 'Netflix' }))

    expect(screen.getByRole('button', { name: 'Добавить выбранные' })).toBeDisabled()
    expect(screen.getByText('Выберите, что сделать')).toBeInTheDocument()
  })

  it('shows elements the server did not apply as a normal outcome', async () => {
    const user = userEvent.setup()
    await uploadFixture(user)
    state.confirmResponse = {
      status: 201,
      body: {
        import_id: 'imp_1',
        status: 'confirmed',
        created: [
          { candidate_id: 'cnd_1', subscription_id: 10, name: 'Claude.ai', amount: '20.00', billing_cycle: 'monthly', start_date: '2026-07-05', next_billing_date: '2026-11-05', created_despite_duplicate: false },
        ],
        updated: [],
        skipped: [{ candidate_id: 'cnd_netflix', code: 'confirm.amount_conflict', params: { actual_amount: '16.99' } }],
        created_count: 1,
        updated_count: 0,
        skipped_count: 1,
      },
    }
    await user.click(screen.getByRole('button', { name: 'Добавить выбранные' }))

    expect(await screen.findByText(/Добавлено подписок: 1/)).toBeInTheDocument()
    expect(screen.getByText(/Не удалось применить: 1/)).toBeInTheDocument()
    expect(screen.getByText(/сумма подписки изменилась/)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('explains a refusal by its code and keeps the screen usable', async () => {
    const user = userEvent.setup()
    state.importResponse = {
      status: 429,
      body: { detail: { code: 'import.rate_limited', params: { retry_after: '2026-10-29T10:00:00Z' } } },
    }
    renderApp('/import')
    await user.upload(await screen.findByLabelText('Выбрать файл'), file())
    await user.click(screen.getByRole('button', { name: 'Найти подписки' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/Слишком много загрузок/)
    expect(screen.getByRole('button', { name: 'Найти подписки' })).toBeInTheDocument()
  })

  it('falls back to a usable message for a code it does not know', async () => {
    const user = userEvent.setup()
    state.importResponse = { status: 400, body: { detail: { code: 'statement.brand_new_code', params: {} } } }
    renderApp('/import')
    await user.upload(await screen.findByLabelText('Выбрать файл'), file())
    await user.click(screen.getByRole('button', { name: 'Найти подписки' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/Что-то пошло не так/)
  })

  it('restores the candidate list after a reload, by id', async () => {
    const user = userEvent.setup()
    await uploadFixture(user)

    renderApp('/import')
    await waitFor(() => expect(screen.getAllByRole('checkbox', { name: 'Claude.ai' })).not.toHaveLength(0))
  })

  it('undoes the import through the existing subscription endpoints', async () => {
    const user = userEvent.setup()
    await uploadFixture(user)
    state.confirmResponse = {
      status: 201,
      body: {
        import_id: 'imp_1',
        status: 'confirmed',
        created: [
          { candidate_id: 'cnd_1', subscription_id: 10, name: 'Claude.ai', amount: '20.00', billing_cycle: 'monthly', start_date: '2026-07-05', next_billing_date: '2026-11-05', created_despite_duplicate: false },
        ],
        updated: [
          { candidate_id: 'cnd_netflix', subscription_id: 2, name: 'Netflix', previous: { amount: '15.49' }, current: { amount: '17.99' } },
        ],
        skipped: [],
        created_count: 1,
        updated_count: 1,
        skipped_count: 0,
      },
    }
    await user.click(screen.getByRole('button', { name: 'Добавить выбранные' }))
    await screen.findByText(/Добавлено подписок: 1/)
    await user.click(screen.getByRole('button', { name: 'Отменить импорт' }))

    await waitFor(() => {
      expect(state.calls).toContainEqual(expect.objectContaining({ method: 'DELETE', path: '/api/subscriptions/10' }))
      expect(state.calls).toContainEqual(
        expect.objectContaining({ method: 'PATCH', path: '/api/subscriptions/2', body: { amount: '15.49' } }),
      )
    })
  })

  it('never reads the numeric confidence', async () => {
    const user = userEvent.setup()
    await uploadFixture(user)
    const list = within(document.body)
    expect(list.queryByText('90')).not.toBeInTheDocument()
    expect(screen.getAllByText('Уверенно').length).toBeGreaterThan(0)
  })
})

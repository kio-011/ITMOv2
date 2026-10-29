// Responses copied from the agreed contract's examples, so the screen is tested
// against the shape both teams signed, not against what the UI happens to expect.

export const candidate = (over: Partial<Record<string, unknown>> = {}) => ({
  candidate_id: 'cnd_1',
  name: 'Claude.ai',
  amount: '20.00',
  previous_amount: null,
  billing_cycle: 'monthly',
  custom_interval_days: null,
  start_date: '2026-07-05',
  suggested_next_billing_date: '2026-11-05',
  occurrence_count: 4,
  first_seen: '2026-07-05',
  last_seen: '2026-10-05',
  cycle_basis: 'intervals',
  amount_stability: 'stable',
  confidence_label: 'high',
  preselect_recommended: true,
  duplicate_match: 'none',
  matched_subscription: null,
  occurrences: [
    { line: 4, date: '2026-07-05', amount: '20.00', raw_description: 'CLAUDE.AI SUBSCRIPTION' },
  ],
  confidence: 90,
  confidence_parts: { repeats: 30, dates: 30, amount: 20, text: 10 },
  ...over,
})

export const netflixDuplicate = candidate({
  candidate_id: 'cnd_netflix',
  name: 'Netflix',
  amount: '17.99',
  previous_amount: '15.49',
  amount_stability: 'price_step',
  confidence_label: 'high',
  preselect_recommended: false,
  duplicate_match: 'amount_differs',
  matched_subscription: { id: 2, name: 'Netflix', amount: '15.49', billing_cycle: 'monthly' },
})

export const githubReview = candidate({
  candidate_id: 'cnd_github',
  name: 'Github Pro Annual',
  amount: '100.00',
  billing_cycle: 'yearly',
  occurrence_count: 1,
  cycle_basis: 'text',
  amount_stability: 'single',
  confidence_label: 'low',
  preselect_recommended: false,
  confidence: 30,
})

export const importBody = (over: Partial<Record<string, unknown>> = {}) => ({
  import_id: 'imp_1',
  status: 'analyzed',
  expires_at: '2026-10-29T11:00:00Z',
  ruleset_version: '2026-10-29.2',
  statement: {
    filename: 'statement-sample.csv',
    encoding: 'utf-8',
    delimiter: ',',
    currency: 'USD',
    period_start: '2026-07-01',
    period_end: '2026-10-25',
    rows_total: 38,
    rows_parsed: 37,
    rows_skipped: 1,
    incomplete_data: true,
    skipped_rows: [{ line: 26, code: 'row.amount_missing', raw: '...' }],
    skipped_by_code: { 'row.amount_missing': 1 },
    rejected_groups: { 'rejected.inflow': 1 },
  },
  candidates: [candidate(), netflixDuplicate],
  candidates_review: [githubReview],
  ...over,
})

// Types are camelCase: the API client converts snake_case keys at the boundary.
// Money fields are decimal strings and are never turned into numbers.
export type BillingCycle = 'monthly' | 'yearly' | 'weekly' | 'custom_days'
export type Plan = 'free' | 'pro'

export interface User {
  id: number
  email: string
  plan: Plan
  defaultCurrency: string
}

export interface Tokens {
  accessToken: string
  refreshToken: string
}

export interface Summary {
  monthlyTotal: string
  yearlyTotal: string
  currency: string
}

export interface SubscriptionShare {
  id: number
  name: string
  billingCycle: BillingCycle
  monthlyCost: string
  sharePercent: string
}

export interface Breakdown {
  currency: string
  monthlyTotal: string
  bySubscription: SubscriptionShare[]
}

export interface UpcomingCharge {
  id: number
  name: string
  amount: string
  billingCycle: BillingCycle
  chargeDate: string
  daysUntil: number
}

export interface Subscription {
  id: number
  name: string
  amount: string
  billingCycle: BillingCycle
  customIntervalDays: number | null
  isActive: boolean
  startDate: string
  nextBillingDate: string
  note: string | null
}

export interface SubscriptionListItem extends Subscription {
  monthlyCost: string
  chargeDate: string | null
  daysUntil: number | null
}

export interface SubscriptionInput {
  name: string
  amount: string
  billingCycle: BillingCycle
  customIntervalDays: number | null
  startDate: string
  note: string | null
  isActive: boolean
}

export type SortField = 'charge_date' | 'amount' | 'monthly_cost' | 'name'

export interface ListParams {
  isActive?: boolean
  billingCycle?: BillingCycle
  q?: string
  sort?: SortField
  order?: 'asc' | 'desc'
}

// --- Statement import ------------------------------------------------------
// Field names follow the contract agreed between the two teams; the client
// never reads the numeric `confidence`, only the label and the two lists.

export type DuplicateMatch = 'none' | 'exact' | 'amount_differs' | 'cycle_differs'
export type ConfidenceLabel = 'high' | 'medium' | 'low'
export type CandidateAction = 'create' | 'update' | 'skip'

export interface CandidateOccurrence {
  line: number
  date: string
  amount: string
  rawDescription: string
}

export interface MatchedSubscription {
  id: number
  name: string
  amount: string
  billingCycle: BillingCycle
}

export interface ImportCandidate {
  candidateId: string
  name: string
  amount: string
  previousAmount: string | null
  billingCycle: BillingCycle
  customIntervalDays: number | null
  startDate: string
  suggestedNextBillingDate: string
  occurrenceCount: number
  firstSeen: string
  lastSeen: string
  cycleBasis: 'intervals' | 'single_interval' | 'text'
  amountStability: 'stable' | 'near_stable' | 'price_step' | 'single'
  confidenceLabel: ConfidenceLabel
  preselectRecommended: boolean
  duplicateMatch: DuplicateMatch
  matchedSubscription: MatchedSubscription | null
  occurrences: CandidateOccurrence[]
}

export interface StatementFacts {
  filename: string
  currency: string
  rowsTotal: number
  rowsParsed: number
  rowsSkipped: number
  incompleteData: boolean
  skippedRows: { line: number; code: string; raw: string }[]
  skippedByCode: Record<string, number>
  rejectedGroups: Record<string, number>
}

export interface StatementImport {
  importId: string
  status: string
  expiresAt: string
  statement: StatementFacts
  candidates: ImportCandidate[]
  candidatesReview: ImportCandidate[]
}

export interface ConfirmItemInput {
  candidateId: string
  action?: 'create' | 'update'
  targetSubscriptionId?: number
  expectedAmount?: string
  amount?: string
}

export interface ConfirmResult {
  importId: string
  created: {
    candidateId: string
    subscriptionId: number
    name: string
    amount: string
    billingCycle: BillingCycle
  }[]
  updated: {
    candidateId: string
    subscriptionId: number
    name: string
    previous: { amount: string }
    current: { amount: string }
  }[]
  skipped: { candidateId: string; code: string; params: Record<string, string> }[]
  createdCount: number
  updatedCount: number
  skippedCount: number
}

/**
 * Who may change what on a pricing screen.
 *
 * The spec splits the levers in two (FR-007a, FR-007b):
 *
 * - **Monetary policy** — labour rates, margin basis, target margin, fee
 *   rules, channel economics, the overhead pool, machine cost policy, the
 *   rounding rule, the free-shipping threshold — needs an admin or an owner,
 *   because each is a decision about money.
 * - **Operational item figures** — print time, waste, batching, failure mode,
 *   finishing minutes, measured packaging quantities — are open to a member,
 *   because they are measurements rather than decisions.
 *
 * Costs and margins are visible to everyone, a viewer included (FR-007c).
 *
 * ## This is not the authorisation
 *
 * The API refuses an insufficient role on its own and leaves the figure
 * untouched (FR-007d). These helpers decide only what a screen *offers*, so
 * that a viewer meets a control that is present and disabled rather than a
 * control that vanished — the edge case under FR-007c asks for "unavailable
 * rather than hidden", because a figure whose editor disappeared is a figure
 * the reader cannot explain.
 *
 * An absent role (an older token, a user outside any tenant) is treated as
 * read-only. Offering a control the API will refuse is the worse of the two
 * failures: the operator fills a form and loses the work at submit.
 */

import type { TenantRole, User } from '@/lib/auth'

/** Roles that may change a figure about money. */
const MONETARY_ROLES: readonly TenantRole[] = ['owner', 'admin']

/** Roles that may change a measurement of an item. */
const OPERATIONAL_ROLES: readonly TenantRole[] = ['owner', 'admin', 'member']

function roleOf(user: Pick<User, 'role'> | null | undefined): TenantRole | null {
  return user?.role ?? null
}

/**
 * May this user change monetary policy (FR-007a)?
 *
 * Labour rates, margin basis, target margin, fee rules, channel economics,
 * overhead, machine cost policy, rounding and the free-shipping threshold.
 */
export function canEditMonetaryPolicy(user: Pick<User, 'role'> | null | undefined): boolean {
  const role = roleOf(user)
  return role !== null && MONETARY_ROLES.includes(role)
}

/**
 * May this user change an item's operational figures (FR-007b)?
 *
 * Print time, waste allowance, batching quantity, failure mode, finishing and
 * handling minutes, measured packaging quantities.
 */
export function canEditOperationalFigures(user: Pick<User, 'role'> | null | undefined): boolean {
  const role = roleOf(user)
  return role !== null && OPERATIONAL_ROLES.includes(role)
}

/**
 * May this user read costs and margins?
 *
 * Always, for every role including a viewer (FR-007c). It exists as a function
 * so a screen can express the rule rather than assume it, and so that a future
 * change has one place to break rather than thirty.
 */
// The argument is deliberately unused: it is what makes the rule expressible
// at a call site, and what a future change to FR-007c would read.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function canViewCosts(user: Pick<User, 'role'> | null | undefined): boolean {
  return true
}

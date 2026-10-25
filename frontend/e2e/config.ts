/**
 * E2E Test Configuration
 *
 * Centralized configuration for E2E tests.
 * Uses environment variables with sensible defaults.
 *
 * Every default points at a local stack (T267). An unconfigured run used to
 * aim at production; a run with nothing set now aims at localhost, and only
 * an explicit PLAYWRIGHT_API_URL / PLAYWRIGHT_BASE_URL reaches anything else.
 */

// API URL for backend requests
export const API_URL = process.env.PLAYWRIGHT_API_URL || 'http://localhost:8000'

// Health check endpoint
export const HEALTH_URL = `${API_URL}/health`

/**
 * The dedicated tenant the pricing journeys run against (T266), seeded by
 * `backend/scripts/seed_e2e.py`. Test values for that tenant only -- never
 * the production account (Constitution II).
 */
export const E2E_OWNER_EMAIL = process.env.E2E_OWNER_EMAIL || 'e2e-owner@example.com'
export const E2E_VIEWER_EMAIL = process.env.E2E_VIEWER_EMAIL || 'e2e-viewer@example.com'
export const E2E_PASSWORD = process.env.E2E_PASSWORD || 'E2e-Pricing-Only-1'

/** Names the seed gives the catalogue the pricing journeys work on. */
export const E2E_PRODUCT = 'E2E Dragon Figure'
export const E2E_CHANNEL = 'E2E Marketplace'

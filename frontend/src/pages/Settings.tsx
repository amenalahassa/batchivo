/**
 * Settings Page
 *
 * Main settings page with tabs for different configuration sections.
 */

import { AppLayout } from '@/components/layout/AppLayout'
import { EstimateProposalList } from '@/components/pricing/EstimateProposalList'
import { ExchangeRatePanel } from '@/components/pricing/ExchangeRatePanel'
import { EtsySettings } from '@/components/settings/EtsySettings'
import { ShippingProfilesPanel } from '@/components/settings/ShippingProfilesPanel'
import { GeneralSettings } from '@/components/settings/GeneralSettings'
import { PricingPolicySettings } from '@/components/settings/PricingPolicySettings'
import { MarginDivergencePanel } from '@/components/pricing/MarginDivergencePanel'
import { SquareSettings } from '@/components/settings/SquareSettings'
import { TeamSettings } from '@/components/settings/TeamSettings'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useAuth } from '@/contexts/AuthContext'
import { canEditMonetaryPolicy } from '@/lib/pricing/permissions'
import { Building2, Coins, CreditCard, Store, Users } from 'lucide-react'

export function Settings() {
  const { user } = useAuth()
  // A viewer or member reads the policy and meets disabled controls, rather
  // than a tab that is not there (FR-007a, FR-007c).
  const canEditPricing = canEditMonetaryPolicy(user)

  return (
    <AppLayout>
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Settings</h1>
          <p className="text-muted-foreground">
            Manage your organization settings and integrations
          </p>
        </div>

        <Tabs defaultValue="general" className="space-y-6">
          <TabsList>
            <TabsTrigger value="general" className="gap-2">
              <Building2 className="h-4 w-4" />
              General
            </TabsTrigger>
            <TabsTrigger value="pricing" className="gap-2">
              <Coins className="h-4 w-4" />
              Pricing
            </TabsTrigger>
            <TabsTrigger value="payments" className="gap-2">
              <CreditCard className="h-4 w-4" />
              Payments
            </TabsTrigger>
            <TabsTrigger value="marketplace" className="gap-2">
              <Store className="h-4 w-4" />
              Marketplace
            </TabsTrigger>
            <TabsTrigger value="team" className="gap-2">
              <Users className="h-4 w-4" />
              Team
            </TabsTrigger>
          </TabsList>

          <TabsContent value="general">
            <GeneralSettings />
          </TabsContent>

          <TabsContent value="pricing" className="space-y-6">
            <PricingPolicySettings canEdit={canEditPricing} />
            {/*
              The proposals this screen's own thresholds produce (FR-042b): an
              observation that diverged too far to apply on its own waits here
              for the operator to accept or reject it as a whole (FR-042c).
              It sits beside the thresholds because the two are one decision —
              tighten the threshold and more land here.
            */}
            <EstimateProposalList />
            {/*
              The other consequence of this screen's thresholds (FR-042, US7
              scenario 3): a settled line that earned a different margin than
              it was sold at. The periodic sweep emails the operator about
              these; this is where they read them, and it sits beside the
              threshold for the same reason the proposals do — tighten it and
              more land here.
            */}
            <MarginDivergencePanel />
            {/*
              A settled sale in another currency that froze no rate cannot
              state its margin; the operator gives it one here (FR-028h).
            */}
            <ExchangeRatePanel canEdit={canEditPricing} />
            {/* Postage every margin deducts, by zone and weight (FR-024, T245). */}
            <ShippingProfilesPanel canEdit={canEditPricing} />
          </TabsContent>

          <TabsContent value="payments">
            <SquareSettings />
          </TabsContent>

          <TabsContent value="marketplace">
            <EtsySettings />
          </TabsContent>

          <TabsContent value="team">
            <TeamSettings />
          </TabsContent>
        </Tabs>
      </div>
    </AppLayout>
  )
}

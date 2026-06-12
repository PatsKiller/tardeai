import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import SchwabAccountsMonitor from '../components/SchwabAccountsMonitor'
import { fmt$ } from '../lib/format'
import type { DrillContext } from '../components/DetailDrawer'
import ProtectionPanel from '../components/ProtectionPanel'
import ProposalsRich from '../components/ProposalsRich'
import BrokerOrders from '../components/BrokerOrders'
import TimeExitProposals from '../components/TimeExitProposals'
import ATMControlPanel from '../components/ATMControlPanel'
import OpenTradesIntelligence from '../components/OpenTradesIntelligence'
import ProAnalystPill, { useProAnalystMap } from '../components/ProAnalystPill'
import ManualTosDesk from './ManualTosDesk'

interface Props { onDrill: (ctx: DrillContext) => void }
const TABS = ['Trade AI', 'Open Trades', 'Proposals', 'Manual ToS', 'Execution', 'Broker Recon', 'Scalp', 'ATM Controls', 'Broker Orders', 'Schwab Accounts'] as const

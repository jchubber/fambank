import { useEffect, useState } from 'react'
import { formatCurrency } from '../utils/currency'

interface Props {
  token: string
  apiUrl: string
  currencySymbol: string
}

interface ChildProfileData {
  interest_rate: number
  penalty_interest_rate: number
  cd_penalty_rate: number
}

interface TreasuryYield {
  id: number
  yield_date: string
  yield_value: number
  created_at: string
}

interface Multipliers {
  savings_multiplier: number
  college_savings_multiplier: number
}

interface WithdrawalRequest {
  id: number
  child_id: number
  amount: number
  memo?: string | null
  status: string
  denial_reason?: string | null
}

interface Badge {
  id: number
  name: string
  module_id?: number | null
}

export default function ChildProfile({ token, apiUrl, currencySymbol }: Props) {
  const [data, setData] = useState<ChildProfileData | null>(null)
  const [withdrawals, setWithdrawals] = useState<WithdrawalRequest[]>([])
  const [badges, setBadges] = useState<Badge[]>([])
  const [treasuryYield, setTreasuryYield] = useState<TreasuryYield | null>(null)
  const [multipliers, setMultipliers] = useState<Multipliers | null>(null)

  useEffect(() => {
    const fetchData = async () => {
      const resp = await fetch(`${apiUrl}/children/me`, { headers: { Authorization: `Bearer ${token}` } })
      if (resp.ok) setData((await resp.json()) as ChildProfileData)
    }
    const fetchWithdrawals = async () => {
      const resp = await fetch(`${apiUrl}/withdrawals/mine`, { headers: { Authorization: `Bearer ${token}` } })
      if (resp.ok) setWithdrawals(await resp.json())
    }
    const fetchBadges = async () => {
      const resp = await fetch(`${apiUrl}/education/badges/me`, { headers: { Authorization: `Bearer ${token}` } })
      if (resp.ok) setBadges(await resp.json())
    }
    const fetchTreasuryYield = async () => {
      const resp = await fetch(`${apiUrl}/settings/treasury-yields?limit=1`)
      if (resp.ok) {
        const yields = await resp.json() as TreasuryYield[]
        if (yields.length > 0) setTreasuryYield(yields[0])
      }
    }
    const fetchMultipliers = async () => {
      const resp = await fetch(`${apiUrl}/settings/multipliers`)
      if (resp.ok) setMultipliers(await resp.json() as Multipliers)
    }
    fetchData()
    fetchWithdrawals()
    fetchBadges()
    fetchTreasuryYield()
    fetchMultipliers()
  }, [token, apiUrl])

  if (!data) return <p>Loading...</p>

  return (
    <div className="container">
      <h2>Your Profile</h2>
      {treasuryYield && (
        <div style={{ padding: '0.75rem', backgroundColor: '#f0f8ff', borderRadius: '4px', marginBottom: '1rem', border: '1px solid #b0d4f1' }}>
          <p style={{ margin: 0, fontWeight: 'bold' }}>
            Current Treasury Rate: {treasuryYield.yield_value.toFixed(2)}%
          </p>
          <p style={{ margin: '0.25rem 0 0 0', fontSize: '0.9em', color: '#666' }}>
            This is the base rate that your savings interest is calculated from (as of {new Date(treasuryYield.yield_date).toLocaleDateString()})
          </p>
        </div>
      )}
      <p>
        <strong>Interest rate: {(data.interest_rate * 100).toFixed(2)}%</strong> - This is how much extra money you earn for saving.
        {treasuryYield && multipliers && (
          <span style={{ fontSize: '0.9em', color: '#666', display: 'block', marginTop: '0.25rem' }}>
            (Calculated from Treasury Rate {treasuryYield.yield_value.toFixed(2)}% × Multiplier {multipliers.savings_multiplier.toFixed(2)}x)
          </span>
        )}
      </p>
      <p>
        Penalty rate: {(data.penalty_interest_rate * 100).toFixed(2)}% - If your balance goes below zero, you owe this extra.
      </p>
      <p>
        CD penalty rate: {(data.cd_penalty_rate * 100).toFixed(2)}% - Taking money out of a CD early costs this much.
      </p>
      {withdrawals.length > 0 && (
        <div>
          <h3>Your Money Requests</h3>
          <ul className="list">
            {withdrawals.map(w => (
              <li key={w.id}>
                {formatCurrency(w.amount, currencySymbol)}{w.memo ? ` (${w.memo})` : ''} - {w.status}
                {w.denial_reason ? ` (Reason: ${w.denial_reason})` : ''}
              </li>
            ))}
          </ul>
        </div>
      )}
      {badges.length > 0 && (
        <div>
          <h3>Your Badges</h3>
          <ul className="list">
            {badges.map(b => (
              <li key={b.id}>{b.name}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

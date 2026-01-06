import { useState, type FormEvent } from 'react'

interface SiteSettings {
  savings_multiplier: number
  college_savings_multiplier: number
}

interface TreasuryYield {
  id: number
  yield_date: string
  yield_value: number
  created_at: string
}

interface Props {
  settings: SiteSettings
  treasuryYield: TreasuryYield
  token: string
  apiUrl: string
  onClose: () => void
  onSaved: () => void
}

export default function EditMultipliersModal({ settings, treasuryYield, token, apiUrl, onClose, onSaved }: Props) {
  const [savingsMultiplier, setSavingsMultiplier] = useState(settings.savings_multiplier.toString())
  const [collegeSavingsMultiplier, setCollegeSavingsMultiplier] = useState(settings.college_savings_multiplier.toString())
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setLoading(true)

    try {
      // Update savings multiplier
      const savingsResp = await fetch(`${apiUrl}/settings/multipliers`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          account_type: 'savings',
          multiplier: Number(savingsMultiplier),
        }),
      })

      if (!savingsResp.ok) {
        throw new Error('Failed to update savings multiplier')
      }

      // Update college savings multiplier
      const collegeResp = await fetch(`${apiUrl}/settings/multipliers`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          account_type: 'college_savings',
          multiplier: Number(collegeSavingsMultiplier),
        }),
      })

      if (!collegeResp.ok) {
        throw new Error('Failed to update college savings multiplier')
      }

      onSaved()
      onClose()
    } catch (error) {
      console.error('Error updating multipliers:', error)
      alert('Failed to update multipliers. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const savingsRate = treasuryYield.yield_value * Number(savingsMultiplier)
  const collegeSavingsRate = treasuryYield.yield_value * Number(collegeSavingsMultiplier)

  return (
    <div className="modal-overlay">
      <div className="modal">
        <h3>Edit Interest Rate Multipliers</h3>
        <p style={{ marginBottom: '1rem', fontSize: '0.9em', color: '#666' }}>
          Current Treasury Yield: <strong>{treasuryYield.yield_value.toFixed(2)}%</strong> (as of {new Date(treasuryYield.yield_date).toLocaleDateString()})
        </p>
        <form onSubmit={handleSubmit} className="form">
          <label>
            Savings Account Multiplier
            <input
              type="number"
              step="0.01"
              min="0"
              value={savingsMultiplier}
              onChange={(e) => setSavingsMultiplier(e.target.value)}
              required
            />
            {!Number.isNaN(Number(savingsMultiplier)) && (
              <span style={{ fontSize: '0.9em', color: '#666', marginLeft: '0.5rem' }}>
                → Calculated Rate: {savingsRate.toFixed(2)}%
              </span>
            )}
          </label>
          <label>
            College Savings Account Multiplier
            <input
              type="number"
              step="0.01"
              min="0"
              value={collegeSavingsMultiplier}
              onChange={(e) => setCollegeSavingsMultiplier(e.target.value)}
              required
            />
            {!Number.isNaN(Number(collegeSavingsMultiplier)) && (
              <span style={{ fontSize: '0.9em', color: '#666', marginLeft: '0.5rem' }}>
                → Calculated Rate: {collegeSavingsRate.toFixed(2)}%
              </span>
            )}
          </label>
          <div className="modal-actions">
            <button type="submit" disabled={loading}>
              {loading ? 'Saving...' : 'Save'}
            </button>
            <button type="button" className="ml-1" onClick={onClose} disabled={loading}>
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}


import { useCallback, useEffect, useState } from 'react'
import { formatCurrency } from '../utils/currency'
import { useToast } from '../components/ToastProvider'

interface Child {
  id: number
  first_name: string
}

interface Loan {
  id: number
  amount: number
  purpose?: string | null
  interest_rate: number
  status: string
  principal_remaining: number
  terms?: string | null
}

interface Props {
  token: string
  apiUrl: string
  currencySymbol: string
  isAdmin: boolean
}

export default function ParentLoans({ token, apiUrl, currencySymbol, isAdmin }: Props) {
  const [children, setChildren] = useState<Child[]>([])
  const [selectedChild, setSelectedChild] = useState<number | null>(null)
  const [loans, setLoans] = useState<Loan[]>([])
  const [approveRate, setApproveRate] = useState<Record<number, string>>({})
  const [approveTerms, setApproveTerms] = useState<Record<number, string>>({})
  const [paymentAmount, setPaymentAmount] = useState<Record<number, string>>({})
  const [newRate, setNewRate] = useState<Record<number, string>>({})
  const [loansUiEnabled, setLoansUiEnabled] = useState(true)
  const { showToast } = useToast()

  const fetchChildren = useCallback(async () => {
    const resp = await fetch(`${apiUrl}/children/`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (resp.ok) setChildren(await resp.json())
  }, [apiUrl, token])

  const fetchLoans = useCallback(
    async (cid: number) => {
      const resp = await fetch(`${apiUrl}/loans/child/${cid}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (resp.ok) setLoans(await resp.json())
    },
    [apiUrl, token],
  )

  const fetchSettings = useCallback(async () => {
    const resp = await fetch(`${apiUrl}/settings/`)
    if (resp.ok) {
      const data = await resp.json()
      setLoansUiEnabled(data.loans_ui_enabled !== undefined ? data.loans_ui_enabled : true)
    }
  }, [apiUrl])

  const toggleLoansUi = async () => {
    const newValue = !loansUiEnabled
    const resp = await fetch(`${apiUrl}/settings/`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ loans_ui_enabled: newValue }),
    })
    if (resp.ok) {
      setLoansUiEnabled(newValue)
      showToast(newValue ? 'Loans UI enabled for children' : 'Loans UI disabled for children')
    } else {
      showToast('Failed to update setting', 'error')
    }
  }

  useEffect(() => {
    fetchChildren()
    fetchSettings()
  }, [fetchChildren, fetchSettings])

  useEffect(() => {
    if (selectedChild) fetchLoans(selectedChild)
  }, [selectedChild, fetchLoans])

  const approveLoan = async (loanId: number) => {
    const body = {
      interest_rate: parseFloat(approveRate[loanId] || '0') / 100,
      terms: approveTerms[loanId] || undefined,
    }
    await fetch(`${apiUrl}/loans/${loanId}/approve`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    })
    fetchLoans(selectedChild!)
  }

  const denyLoan = async (loanId: number) => {
    await fetch(`${apiUrl}/loans/${loanId}/deny`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
    fetchLoans(selectedChild!)
  }

  const recordPayment = async (loanId: number) => {
    await fetch(`${apiUrl}/loans/${loanId}/payment`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ amount: parseFloat(paymentAmount[loanId] || '0') }),
    })
    setPaymentAmount({ ...paymentAmount, [loanId]: '' })
    fetchLoans(selectedChild!)
  }

  const changeRate = async (loanId: number) => {
    await fetch(`${apiUrl}/loans/${loanId}/interest`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ interest_rate: parseFloat(newRate[loanId] || '0') / 100 }),
    })
    setNewRate({ ...newRate, [loanId]: '' })
    fetchLoans(selectedChild!)
  }

  const closeLoan = async (loanId: number) => {
    await fetch(`${apiUrl}/loans/${loanId}/close`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
    fetchLoans(selectedChild!)
  }

  return (
    <div className="container">
      <h2>Manage Loans</h2>
      {isAdmin && (
        <div style={{ marginBottom: '1rem' }}>
          <button onClick={toggleLoansUi}>
            {loansUiEnabled ? 'Disable Loans UI for Children' : 'Enable Loans UI for Children'}
          </button>
        </div>
      )}
      Loans are useful when your child wants to borrow money for something special, like a new game or a bike. You can approve or deny their requests, and help them learn about interest rates and payments.
      <p>Once a loan is approved, you'll see a credit in your child's account for the full loan amount. You should then deduct whatever they bought with the loan out as a new transaction (e.g., "New Phone"). </p>

      <p>Note that the system doesn't automatically parse your "terms", so if you say "0% for the first month, then 5%", you'll need to come back here after 30 days and change the interest rate to 5% from 0. </p>
      <div>
        <label>
          Child:
          <select
            value={selectedChild ?? ''}
            onChange={e => setSelectedChild(Number(e.target.value))}
          >
            <option value="" disabled>
              Select...
            </option>
            {children.map(c => (
              <option key={c.id} value={c.id}>
                {c.first_name}
              </option>
            ))}
          </select>
        </label>
      </div>
      {loans.length > 0 && (
        <ul className="list">
          {loans.map(l => (
            <li key={l.id}>
              {formatCurrency(l.amount, currencySymbol)} for {l.purpose || 'n/a'} - {l.status}
              {['approved', 'active'].includes(l.status) && (
                <div>
                  Rate: {(l.interest_rate * 100).toFixed(2)}%
                  <input
                    placeholder="New rate (%)"
                    value={newRate[l.id] || ''}
                    onChange={e =>
                      setNewRate({ ...newRate, [l.id]: e.target.value })
                    }
                  />
                  <button onClick={() => changeRate(l.id)}>Update Rate</button>
                </div>
              )}
              {l.status === 'requested' && (
                <div>
                  <input
                    placeholder="Interest rate (%)"
                    value={approveRate[l.id] || ''}
                    onChange={e =>
                      setApproveRate({ ...approveRate, [l.id]: e.target.value })
                    }
                  />
                  <input
                    placeholder="Terms"
                    value={approveTerms[l.id] || ''}
                    onChange={e =>
                      setApproveTerms({ ...approveTerms, [l.id]: e.target.value })
                    }
                  />
                  <button onClick={() => approveLoan(l.id)}>Approve</button>
                  <button onClick={() => denyLoan(l.id)}>Deny</button>
                </div>
              )}
              {l.status === 'active' && (
                <div>
                  Remaining: {formatCurrency(l.principal_remaining, currencySymbol)}
                  <input
                    placeholder="Payment amount"
                    value={paymentAmount[l.id] || ''}
                    onChange={e =>
                      setPaymentAmount({ ...paymentAmount, [l.id]: e.target.value })
                    }
                  />
                  <button onClick={() => recordPayment(l.id)}>Record Payment</button>
                  <button onClick={() => closeLoan(l.id)}>Close</button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}


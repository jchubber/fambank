import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import ConfirmModal from '../components/ConfirmModal'
import LedgerTable from '../components/LedgerTable'
import { formatCurrency } from '../utils/currency'
import { useToast } from '../components/ToastProvider'

interface Transaction {
  id: number
  child_id: number
  type: string
  amount: number
  memo?: string | null
  initiated_by: string
  initiator_id: number
  timestamp: string
}

interface LedgerResponse {
  balance: number
  transactions: Transaction[]
}

interface Account {
  id: number
  account_type: string
  balance: number
  available_balance: number | null
  interest_rate: number
  lockup_period_days: number | null
}

interface AccountsResponse {
  checking: Account
  savings: Account
  college_savings: Account
  total_balance: number
}

interface WithdrawalRequest {
  id: number
  child_id: number
  account_type: string
  amount: number
  memo?: string | null
  status: string
  requested_at: string
  responded_at?: string | null
  denial_reason?: string | null
}

interface RecurringCharge {
  id: number
  child_id: number
  amount: number
  type: string
  memo?: string | null
  interval_days: number
  next_run: string
  active: boolean
}

interface Props {
  token: string
  childId: number
  apiUrl: string
  onLogout: () => void
  currencySymbol: string
  loansUiEnabled?: boolean
}

interface CdOffer {
  id: number
  amount: number
  interest_rate: number
  term_days: number
  status: string
  matures_at?: string | null
}

export default function ChildDashboard({ token, childId, apiUrl, onLogout, currencySymbol, loansUiEnabled = true }: Props) {
  const [accounts, setAccounts] = useState<AccountsResponse | null>(null)
  const [ledger, setLedger] = useState<LedgerResponse | null>(null)
  const [withdrawals, setWithdrawals] = useState<WithdrawalRequest[]>([])
  const [cds, setCds] = useState<CdOffer[]>([])
  const [charges, setCharges] = useState<RecurringCharge[]>([])
  const [withdrawAmount, setWithdrawAmount] = useState('')
  const [withdrawMemo, setWithdrawMemo] = useState('')
  const [withdrawAccountType, setWithdrawAccountType] = useState('checking')
  const [selectedAccountId, setSelectedAccountId] = useState<number | null>(null)
  const [confirmAction, setConfirmAction] = useState<{ message: string; onConfirm: () => void } | null>(null)
  const [childName, setChildName] = useState('')
  const [tableWidth, setTableWidth] = useState<number>()
  const { showToast } = useToast()
  const [loadingLedger, setLoadingLedger] = useState(false)

  const fetchAccounts = useCallback(async () => {
    try {
      const resp = await fetch(`${apiUrl}/children/${childId}/accounts`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (resp.ok) {
        const data = await resp.json()
        setAccounts(data)
        // Default to checking account for transaction view
        if (!selectedAccountId && data.checking) {
          setSelectedAccountId(data.checking.id)
        }
      } else {
        showToast('Failed to load accounts', 'error')
      }
    } catch (error) {
      showToast('Failed to load accounts', 'error')
    }
  }, [apiUrl, childId, token, showToast, selectedAccountId])

  const fetchLedger = useCallback(async (accountId?: number | null) => {
    setLoadingLedger(true)
    try {
      const url = accountId 
        ? `${apiUrl}/transactions/child/${childId}?account_id=${accountId}`
        : `${apiUrl}/transactions/child/${childId}`;
      const resp = await fetch(url, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (resp.ok) setLedger(await resp.json())
      else showToast('Failed to load ledger', 'error')
    } finally {
      setLoadingLedger(false)
    }
  }, [apiUrl, childId, token, showToast])

  const fetchMyWithdrawals = useCallback(async () => {
    const resp = await fetch(`${apiUrl}/withdrawals/mine`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (resp.ok) setWithdrawals(await resp.json())
  }, [apiUrl, token])

  const cancelWithdrawal = async (id: number) => {
    const resp = await fetch(`${apiUrl}/withdrawals/${id}/cancel`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
    if (resp.ok) {
      showToast('Withdrawal cancelled')
      fetchMyWithdrawals()
    } else {
      showToast('Failed to cancel', 'error')
    }
  }

  const fetchCds = useCallback(async () => {
    const resp = await fetch(`${apiUrl}/cds/child`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (resp.ok) setCds((await resp.json()) as CdOffer[])
  }, [apiUrl, token])

  const fetchChildName = useCallback(async () => {
    const resp = await fetch(`${apiUrl}/children/${childId}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (resp.ok) {
      const data = await resp.json()
      setChildName(data.first_name)
    }
  }, [apiUrl, childId, token])

  const fetchCharges = useCallback(async () => {
    const resp = await fetch(`${apiUrl}/recurring/mine`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (resp.ok) setCharges(await resp.json())
  }, [apiUrl, token])

  useEffect(() => {
    fetchAccounts()
    fetchMyWithdrawals()
    fetchChildName()
    fetchCds()
    fetchCharges()
  }, [fetchAccounts, fetchMyWithdrawals, fetchChildName, fetchCds, fetchCharges])

  useEffect(() => {
    if (selectedAccountId) {
      fetchLedger(selectedAccountId)
    }
  }, [selectedAccountId, fetchLedger])

  return (
    <div className="container" style={{ width: tableWidth ? `${tableWidth}px` : undefined }}>
      <h2>{childName ? `${childName}'s Accounts` : 'Your Accounts'}</h2>
      {loadingLedger ? (
        <p>Loading...</p>
      ) : (
        accounts && (
        <>
          <div style={{ marginBottom: '2rem' }}>
            <h3>Total Balance: {formatCurrency(accounts.total_balance, currencySymbol)}</h3>
          </div>
          
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: '1rem', marginBottom: '2rem' }}>
            <div style={{ border: '1px solid #ccc', padding: '1rem', borderRadius: '4px' }}>
              <h4>Checking Account</h4>
              <p style={{ fontSize: '1.5rem', fontWeight: 'bold' }}>
                {formatCurrency(accounts.checking.balance, currencySymbol)}
              </p>
              <p className="help-text">No interest earned. Use for everyday transactions.</p>
            </div>
            
            <div style={{ border: '1px solid #ccc', padding: '1rem', borderRadius: '4px' }}>
              <h4>Savings Account</h4>
              <p style={{ fontSize: '1.5rem', fontWeight: 'bold' }}>
                {formatCurrency(accounts.savings.balance, currencySymbol)}
              </p>
              {accounts.savings.available_balance !== null && (
                <p style={{ fontSize: '0.9rem', color: '#666' }}>
                  Available: {formatCurrency(accounts.savings.available_balance, currencySymbol)}
                </p>
              )}
              {accounts.savings.lockup_period_days && (
                <p className="help-text">
                  Lockup period: {accounts.savings.lockup_period_days} days. 
                  Interest rate: {(accounts.savings.interest_rate * 100).toFixed(2)}%
                </p>
              )}
            </div>
            
            <div style={{ border: '1px solid #ccc', padding: '1rem', borderRadius: '4px' }}>
              <h4>College Savings Account</h4>
              <p style={{ fontSize: '1.5rem', fontWeight: 'bold' }}>
                {formatCurrency(accounts.college_savings.balance, currencySymbol)}
              </p>
              <p className="help-text">
                Interest rate: {(accounts.college_savings.interest_rate * 100).toFixed(2)}%. 
                Withdrawals are admin-only for educational expenses.
              </p>
            </div>
          </div>
          
          {ledger && accounts && (
            <>
              <h3>Transactions</h3>
              <div style={{ marginBottom: '1rem' }}>
                <label>
                  Account:
                  <select
                    value={selectedAccountId || ''}
                    onChange={(e) => {
                      const accountId = e.target.value ? parseInt(e.target.value) : null;
                      setSelectedAccountId(accountId);
                    }}
                    style={{ marginLeft: '0.5rem' }}
                  >
                    <option value={accounts.checking.id}>Checking</option>
                    <option value={accounts.savings.id}>Savings</option>
                    <option value={accounts.college_savings.id}>College Savings</option>
                  </select>
                </label>
              </div>
              <p>Balance: {formatCurrency(ledger.balance, currencySymbol)}</p>
              <LedgerTable
                transactions={ledger.transactions}
                onWidth={w => !tableWidth && setTableWidth(w)}
                currencySymbol={currencySymbol}
              />
            </>
          )}
        </>
        )
      )}
      {loansUiEnabled && (
        <div>
          <h4>Borrowing Money (Loans)</h4>
          <p className="help-text">
            Need to buy something but don't have enough saved? You can ask your grown-up for a loan.
            A loan lets you borrow money now and pay it back later, sometimes with a little extra called interest.
            Visit the <Link to="/child/loans">Loans</Link> page to request one or see what you owe.
          </p>
        </div>
      )}
      {charges.length > 0 && (
        <div>
          <h4>Automatic Money Moves</h4>
          <p className="help-text">
            These happen on their own, like getting allowance every week.
          </p>
          <ul className="list">
            {charges.map(c => (
              <li key={c.id}>
                A {c.type} of {formatCurrency(c.amount, currencySymbol)} every {c.interval_days} day(s), next on {new Date(c.next_run + "T00:00:00").toLocaleDateString()} {c.memo ? `(Memo: ${c.memo})` : ''}
              </li>
            ))}
          </ul>
        </div>
      )}
      {cds.length > 0 && (
        <div>
          <h4>Special Savings Offers (CDs)</h4>
          <p className="help-text">
            A CD (Certificate of Deposit) is like a special piggy bank. You agree to leave your money in for a set time and earn extra money called interest.
          </p>
          <ul className="list">
            {cds.map(cd => {
              const daysLeft = cd.matures_at
                ? Math.ceil((new Date(cd.matures_at).getTime() - Date.now()) / 86400000)
                : null
              return (
                <li key={cd.id}>
                  {formatCurrency(cd.amount, currencySymbol)} for {cd.term_days} days at {(cd.interest_rate * 100).toFixed(2)}% - {cd.status}
                  {cd.status === 'accepted' && daysLeft !== null && (
                    <span> (redeems in {daysLeft} days)</span>
                  )}
                  {cd.status === 'accepted' && daysLeft !== null && daysLeft > 0 && (
                    <button
                      onClick={() =>
                        setConfirmAction({
                          message:
                            'Take out this CD early? A 10% fee will be taken.',
                          onConfirm: async () => {
                            await fetch(`${apiUrl}/cds/${cd.id}/redeem-early`, {
                              method: 'POST',
                              headers: { Authorization: `Bearer ${token}` },
                            })
                            fetchCds()
                            fetchLedger(selectedAccountId)
                          },
                        })
                      }
                      className="ml-05"
                    >
                      Take Money Early
                    </button>
                  )}
                  {cd.status === 'offered' && (
                    <>
                      <button
                        onClick={async () => {
                          await fetch(`${apiUrl}/cds/${cd.id}/accept`, {
                            method: 'POST',
                            headers: { Authorization: `Bearer ${token}` },
                          })
                          fetchCds()
                          fetchLedger()
                        }}
                        className="ml-1"
                      >
                        Yes, Save It
                      </button>
                      <button
                        onClick={async () => {
                          await fetch(`${apiUrl}/cds/${cd.id}/reject`, {
                            method: 'POST',
                            headers: { Authorization: `Bearer ${token}` },
                          })
                          fetchCds()
                        }}
                        className="ml-05"
                      >
                        No Thanks
                      </button>
                    </>
                  )}
                </li>
              )
            })}
          </ul>
        </div>
      )}
      <form
        onSubmit={async e => {
          e.preventDefault()
          if (!withdrawAmount) return
          const resp = await fetch(`${apiUrl}/withdrawals/`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify({ 
              amount: Number(withdrawAmount), 
              memo: withdrawMemo || null,
              account_type: withdrawAccountType
            }),
          })
          if (resp.ok) {
            showToast('Withdrawal requested')
            setWithdrawAmount('')
            setWithdrawMemo('')
            setWithdrawAccountType('checking')
            fetchMyWithdrawals()
            fetchAccounts()
          } else {
            showToast('Failed to send request', 'error')
          }
        }}
        className="form"
      >
        <h4>Ask to Take Out Money</h4>
        <p className="help-text">
          A withdrawal is asking your grown-up to send money to you. They have to say yes before you get it.
        </p>
        <label>
          From which account?
          <select
            value={withdrawAccountType}
            onChange={e => setWithdrawAccountType(e.target.value)}
            required
          >
            <option value="checking">Checking Account</option>
            <option value="savings">Savings Account</option>
            <option value="college_savings" disabled>College Savings (Admin Only)</option>
          </select>
        </label>
        {withdrawAccountType === 'savings' && accounts && (
          <p className="help-text" style={{ color: '#666', fontSize: '0.9rem' }}>
            Available: {formatCurrency(accounts.savings.available_balance || 0, currencySymbol)}
          </p>
        )}
        <label>
          How much?
          {currencySymbol}<input
            type="number"
            step="0.01"
            value={withdrawAmount}
            onChange={e => setWithdrawAmount(e.target.value)}
            required
          />
        </label>
        <label>
          Note for your grown-up
          <input
            placeholder="Optional note"
            value={withdrawMemo}
            onChange={e => setWithdrawMemo(e.target.value)}
          />
        </label>
        <button type="submit">Send Request</button>
      </form>
      {withdrawals.length > 0 && (
        <div>
          <h4>Your Money Requests</h4>
          <p className="help-text">Pending means waiting for a grown-up to decide.</p>
          <ul className="list">
              {withdrawals.map(w => (
                <li key={w.id}>
                  {formatCurrency(w.amount, currencySymbol)} from {w.account_type === 'checking' ? 'Checking' : w.account_type === 'savings' ? 'Savings' : 'College Savings'}{w.memo ? ` (${w.memo})` : ''} - {w.status}
                  {w.status === 'pending' && (
                    <button
                      className="ml-05"
                      onClick={() =>
                        setConfirmAction({
                          message: 'Cancel this request?',
                          onConfirm: () => cancelWithdrawal(w.id),
                        })
                      }
                    >
                      Cancel
                    </button>
                  )}
                  {w.denial_reason ? ` (Reason: ${w.denial_reason})` : ''}
                </li>
              ))}
          </ul>
        </div>
      )}
      <button onClick={onLogout}>Logout</button>
      {confirmAction && (
        <ConfirmModal
          message={confirmAction.message}
          onConfirm={() => {
            confirmAction.onConfirm()
            setConfirmAction(null)
          }}
          onCancel={() => setConfirmAction(null)}
        />
      )}
    </div>
  )
}

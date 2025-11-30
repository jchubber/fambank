import { useState, useEffect, type FormEvent } from "react";

interface ChildRates {
  id: number;
  first_name: string;
  interest_rate?: number;
  penalty_interest_rate?: number;
  cd_penalty_rate?: number;
}

interface Account {
  id: number;
  account_type: string;
  balance: number;
  available_balance: number | null;
  interest_rate: number;
  lockup_period_days: number | null;
  penalty_interest_rate?: number | null;
  cd_penalty_rate?: number | null;
}

interface AccountsResponse {
  checking: Account;
  savings: Account;
  college_savings: Account;
  total_balance: number;
}

interface Props {
  child: ChildRates;
  token: string;
  apiUrl: string;
  onClose: () => void;
  onSuccess: (message: string) => void;
  onError: (message: string) => void;
}

export default function EditRatesModal({
  child,
  token,
  apiUrl,
  onClose,
  onSuccess,
  onError,
}: Props) {
  const [accounts, setAccounts] = useState<AccountsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  
  const [savingsInterest, setSavingsInterest] = useState("");
  const [collegeSavingsInterest, setCollegeSavingsInterest] = useState("");
  const [penalty, setPenalty] = useState("");
  const [cdPenalty, setCdPenalty] = useState("");

  useEffect(() => {
    const fetchAccounts = async () => {
      try {
        const resp = await fetch(`${apiUrl}/children/${child.id}/accounts`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (resp.ok) {
          const data: AccountsResponse = await resp.json();
          setAccounts(data);
          setSavingsInterest((data.savings.interest_rate * 100).toString());
          setCollegeSavingsInterest((data.college_savings.interest_rate * 100).toString());
          setPenalty(
            data.checking.penalty_interest_rate != null
              ? (data.checking.penalty_interest_rate * 100).toString()
              : "",
          );
          setCdPenalty(
            data.checking.cd_penalty_rate != null
              ? (data.checking.cd_penalty_rate * 100).toString()
              : "",
          );
        } else {
          onError("Failed to load account information.");
        }
      } catch (err) {
        console.error(err);
        onError("Failed to load account information.");
      } finally {
        setLoading(false);
      }
    };
    fetchAccounts();
  }, [child.id, apiUrl, token, onError]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!accounts) return;
    
    const si = Number(savingsInterest) / 100;
    const csi = Number(collegeSavingsInterest) / 100;
    const p = Number(penalty) / 100;
    const cdr = Number(cdPenalty) / 100;
    
    if (Number.isNaN(si) || Number.isNaN(csi) || Number.isNaN(p) || Number.isNaN(cdr)) {
      onError("Please enter valid numbers for all rates.");
      return;
    }
    
    try {
      // Update savings account interest rate
      const resp1 = await fetch(`${apiUrl}/children/${child.id}/interest-rate`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ interest_rate: si, account_type: "savings" }),
      });
      
      // Update college savings account interest rate
      const resp2 = await fetch(`${apiUrl}/children/${child.id}/interest-rate`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ interest_rate: csi, account_type: "college_savings" }),
      });
      
      // Update penalty interest rate (applies to checking account)
      const resp3 = await fetch(
        `${apiUrl}/children/${child.id}/penalty-interest-rate`,
        {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ penalty_interest_rate: p, account_type: "checking" }),
        },
      );
      
      // Update CD penalty rate (applies to checking account)
      const resp4 = await fetch(
        `${apiUrl}/children/${child.id}/cd-penalty-rate`,
        {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ cd_penalty_rate: cdr }),
        },
      );
      
      if (resp1.ok && resp2.ok && resp3.ok && resp4.ok) {
        onSuccess("Rates updated successfully.");
        onClose();
      } else {
        onError("Failed to update rates.");
      }
    } catch (err) {
      console.error(err);
      onError("Failed to update rates.");
    }
  };

  if (loading) {
    return (
      <div className="modal-overlay">
        <div className="modal">
          <p>Loading account information...</p>
        </div>
      </div>
    );
  }

  if (!accounts) {
    return (
      <div className="modal-overlay">
        <div className="modal">
          <p>Failed to load account information.</p>
          <div className="modal-actions">
            <button type="button" onClick={onClose}>
              Close
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="modal-overlay">
      <div className="modal">
        <h3>Edit Rates for {child.first_name}</h3>
        <form onSubmit={handleSubmit} className="form">
          <div style={{ border: '1px solid #ccc', padding: '1rem', borderRadius: '4px', marginBottom: '1rem' }}>
            <h4>Checking Account</h4>
            <p className="help-text">No interest earned. Used for regular transactions.</p>
            <label title="Penalty for early withdrawal from a certificate of deposit">
              CD penalty rate
              <input
                type="number"
                step="0.01"
                value={cdPenalty}
                onChange={(e) => setCdPenalty(e.target.value)}
                required
              />%
            </label>
          </div>
          
          <div style={{ border: '1px solid #ccc', padding: '1rem', borderRadius: '4px', marginBottom: '1rem' }}>
            <h4>Savings Account</h4>
            <label title="Annual percentage yield paid on savings account">
              Savings Account Interest Rate
              <input
                type="number"
                step="0.01"
                value={savingsInterest}
                onChange={(e) => setSavingsInterest(e.target.value)}
                required
              />%
            </label>
          </div>
          
          <div style={{ border: '1px solid #ccc', padding: '1rem', borderRadius: '4px', marginBottom: '1rem' }}>
            <h4>College Savings Account</h4>
            <label title="Annual percentage yield paid on college savings account">
              College Savings Account Interest Rate
              <input
                type="number"
                step="0.01"
                value={collegeSavingsInterest}
                onChange={(e) => setCollegeSavingsInterest(e.target.value)}
                required
              />%
            </label>
          </div>
          
          <div style={{ border: '1px solid #ccc', padding: '1rem', borderRadius: '4px', marginBottom: '1rem' }}>
            <h4>Penalty Interest Rate</h4>
            <p className="help-text">Rate charged when any account is overdrawn or in penalty (applies to all accounts)</p>
            <label title="Rate charged when an account is overdrawn or in penalty">
              Penalty interest rate
              <input
                type="number"
                step="0.01"
                value={penalty}
                onChange={(e) => setPenalty(e.target.value)}
                required
              />%
            </label>
          </div>
          
          <div className="modal-actions">
            <button type="submit">Save</button>
            <button type="button" className="ml-1" onClick={onClose}>
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

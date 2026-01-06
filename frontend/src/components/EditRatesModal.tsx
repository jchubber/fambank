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

interface Settings {
  savings_account_interest_rate: number;
  college_savings_account_interest_rate: number;
  savings_multiplier: number;
  college_savings_multiplier: number;
  checking_penalty_interest_rate: number;
  savings_penalty_interest_rate: number;
  college_savings_penalty_interest_rate: number;
}

interface TreasuryYield {
  id: number;
  yield_date: string;
  yield_value: number;
  created_at: string;
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
  const [settings, setSettings] = useState<Settings | null>(null);
  const [treasuryYield, setTreasuryYield] = useState<TreasuryYield | null>(null);
  const [loading, setLoading] = useState(true);
  
  const [savingsMultiplier, setSavingsMultiplier] = useState("");
  const [collegeSavingsMultiplier, setCollegeSavingsMultiplier] = useState("");
  const [checkingPenalty, setCheckingPenalty] = useState("");
  const [savingsPenalty, setSavingsPenalty] = useState("");
  const [collegeSavingsPenalty, setCollegeSavingsPenalty] = useState("");
  const [cdPenalty, setCdPenalty] = useState("");

  useEffect(() => {
    const fetchData = async () => {
      try {
        // Fetch settings for global rates
        const settingsResp = await fetch(`${apiUrl}/settings/`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!settingsResp.ok) {
          onError("Failed to load settings.");
          return;
        }
        const settingsData: Settings = await settingsResp.json();
        setSettings(settingsData);
        setSavingsMultiplier(settingsData.savings_multiplier.toString());
        setCollegeSavingsMultiplier(settingsData.college_savings_multiplier.toString());
        setCheckingPenalty((settingsData.checking_penalty_interest_rate * 100).toString());
        setSavingsPenalty((settingsData.savings_penalty_interest_rate * 100).toString());
        setCollegeSavingsPenalty((settingsData.college_savings_penalty_interest_rate * 100).toString());
        
        // Fetch current Treasury yield (get latest)
        try {
          const treasuryResp = await fetch(`${apiUrl}/settings/treasury-yields?limit=1`, {
            headers: { Authorization: `Bearer ${token}` },
          });
          if (treasuryResp.ok) {
            const treasuryData: TreasuryYield[] = await treasuryResp.json();
            if (treasuryData.length > 0) {
              setTreasuryYield(treasuryData[0]);
            }
          }
        } catch (err) {
          console.error("Failed to fetch Treasury yield:", err);
        }
        
        // Fetch accounts for CD penalty rate (still per-child)
        const accountsResp = await fetch(`${apiUrl}/children/${child.id}/accounts`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (accountsResp.ok) {
          const accountsData: AccountsResponse = await accountsResp.json();
          setAccounts(accountsData);
          setCdPenalty(
            accountsData.checking.cd_penalty_rate != null
              ? (accountsData.checking.cd_penalty_rate * 100).toString()
              : "",
          );
        }
      } catch (err) {
        console.error(err);
        onError("Failed to load data.");
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [child.id, apiUrl, token, onError]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!settings || !accounts) return;
    
    const sm = Number(savingsMultiplier);
    const csm = Number(collegeSavingsMultiplier);
    const cp = Number(checkingPenalty) / 100;
    const sp = Number(savingsPenalty) / 100;
    const csp = Number(collegeSavingsPenalty) / 100;
    const cdr = Number(cdPenalty) / 100;
    
    if (Number.isNaN(sm) || Number.isNaN(csm) || Number.isNaN(cp) || 
        Number.isNaN(sp) || Number.isNaN(csp) || Number.isNaN(cdr)) {
      onError("Please enter valid numbers for all rates.");
      return;
    }
    
    try {
      // Update global savings account multiplier
      const resp1 = await fetch(`${apiUrl}/settings/multipliers`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ account_type: "savings", multiplier: sm }),
      });
      
      // Update global college savings account multiplier
      const resp2 = await fetch(`${apiUrl}/settings/multipliers`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ account_type: "college_savings", multiplier: csm }),
      });
      
      // Update global penalty rates
      const resp3 = await fetch(`${apiUrl}/settings/rates/penalty`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ account_type: "checking", rate: cp }),
      });
      
      const resp4 = await fetch(`${apiUrl}/settings/rates/penalty`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ account_type: "savings", rate: sp }),
      });
      
      const resp5 = await fetch(`${apiUrl}/settings/rates/penalty`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ account_type: "college_savings", rate: csp }),
      });
      
      // Update CD penalty rate (still per-child)
      const resp6 = await fetch(
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
      
      if (resp1.ok && resp2.ok && resp3.ok && resp4.ok && resp5.ok && resp6.ok) {
        onSuccess("Multipliers and rates updated successfully. Note: Global multipliers and rates affect all children.");
        onClose();
      } else {
        onError("Failed to update multipliers and rates.");
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

  if (!settings || !accounts) {
    return (
      <div className="modal-overlay">
        <div className="modal">
          <p>Failed to load settings or account information.</p>
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
        <h3>Edit Rates</h3>
        <p style={{ fontStyle: 'italic', marginBottom: '1rem', color: '#666' }}>
          Note: Interest rates are calculated as Treasury Yield × Multiplier. Multipliers and penalty rates are global and affect all children. Only CD penalty rate is per-child.
        </p>
        {treasuryYield && (
          <p style={{ marginBottom: '1rem', padding: '0.5rem', backgroundColor: '#f0f0f0', borderRadius: '4px' }}>
            Current Treasury Yield: <strong>{(treasuryYield.yield_value).toFixed(2)}%</strong> (as of {new Date(treasuryYield.yield_date).toLocaleDateString()})
          </p>
        )}
        <form onSubmit={handleSubmit} className="form">
          <div style={{ border: '1px solid #ccc', padding: '1rem', borderRadius: '4px', marginBottom: '1rem' }}>
            <h4>Savings Account (Global)</h4>
            <label title="Multiplier applied to Treasury Yield to calculate savings account interest rate (applies to all children)">
              Savings Account Multiplier
              <input
                type="number"
                step="0.01"
                value={savingsMultiplier}
                onChange={(e) => setSavingsMultiplier(e.target.value)}
                required
              />
            </label>
            {treasuryYield && savingsMultiplier && !Number.isNaN(Number(savingsMultiplier)) && (
              <p style={{ fontSize: '0.9em', color: '#666', marginTop: '0.5rem' }}>
                Calculated Rate: {treasuryYield.yield_value}% × {savingsMultiplier} = <strong>{(treasuryYield.yield_value * Number(savingsMultiplier)).toFixed(2)}%</strong>
              </p>
            )}
          </div>
          
          <div style={{ border: '1px solid #ccc', padding: '1rem', borderRadius: '4px', marginBottom: '1rem' }}>
            <h4>College Savings Account (Global)</h4>
            <label title="Multiplier applied to Treasury Yield to calculate college savings account interest rate (applies to all children)">
              College Savings Account Multiplier
              <input
                type="number"
                step="0.01"
                value={collegeSavingsMultiplier}
                onChange={(e) => setCollegeSavingsMultiplier(e.target.value)}
                required
              />
            </label>
            {treasuryYield && collegeSavingsMultiplier && !Number.isNaN(Number(collegeSavingsMultiplier)) && (
              <p style={{ fontSize: '0.9em', color: '#666', marginTop: '0.5rem' }}>
                Calculated Rate: {treasuryYield.yield_value}% × {collegeSavingsMultiplier} = <strong>{(treasuryYield.yield_value * Number(collegeSavingsMultiplier)).toFixed(2)}%</strong>
              </p>
            )}
          </div>
          
          <div style={{ border: '1px solid #ccc', padding: '1rem', borderRadius: '4px', marginBottom: '1rem' }}>
            <h4>Penalty Interest Rates (Global)</h4>
            <p className="help-text">Rate charged when an account is overdrawn (applies to all accounts of this type)</p>
            <label title="Penalty rate for checking accounts">
              Checking Account Penalty Rate
              <input
                type="number"
                step="0.01"
                value={checkingPenalty}
                onChange={(e) => setCheckingPenalty(e.target.value)}
                required
              />%
            </label>
            <label title="Penalty rate for savings accounts">
              Savings Account Penalty Rate
              <input
                type="number"
                step="0.01"
                value={savingsPenalty}
                onChange={(e) => setSavingsPenalty(e.target.value)}
                required
              />%
            </label>
            <label title="Penalty rate for college savings accounts">
              College Savings Account Penalty Rate
              <input
                type="number"
                step="0.01"
                value={collegeSavingsPenalty}
                onChange={(e) => setCollegeSavingsPenalty(e.target.value)}
                required
              />%
            </label>
          </div>
          
          <div style={{ border: '1px solid #ccc', padding: '1rem', borderRadius: '4px', marginBottom: '1rem' }}>
            <h4>CD Penalty Rate (Per-Child: {child.first_name})</h4>
            <p className="help-text">Penalty for early withdrawal from a certificate of deposit</p>
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

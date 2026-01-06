import { useState, useEffect, type FormEvent } from 'react'

interface MultiplierHistory {
  id: number
  account_type: string
  date: string
  multiplier: number
  created_at: string
}

interface Props {
  token: string
  apiUrl: string
  accountType: 'savings' | 'college_savings'
  onSaved?: () => void
}

export default function MultiplierHistoryChart({ token, apiUrl, accountType, onSaved }: Props) {
  const [history, setHistory] = useState<MultiplierHistory[]>([])
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editMultiplier, setEditMultiplier] = useState('')
  const [editDate, setEditDate] = useState('')
  const [chartWidth, setChartWidth] = useState(800)
  const [chartHeight] = useState(300)

  const fetchHistory = async () => {
    setLoading(true)
    try {
      const resp = await fetch(
        `${apiUrl}/settings/multipliers/history?account_type=${accountType}`,
        { headers: { Authorization: `Bearer ${token}` } }
      )
      if (resp.ok) {
        const data = await resp.json() as MultiplierHistory[]
        // Sort by date ascending for chart
        data.sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime())
        setHistory(data)
      }
    } catch (error) {
      console.error('Failed to fetch multiplier history:', error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchHistory()
    // Update chart width on mount
    const updateWidth = () => {
      const container = document.getElementById(`chart-container-${accountType}`)
      if (container) {
        setChartWidth(Math.max(600, container.offsetWidth - 40))
      }
    }
    updateWidth()
    window.addEventListener('resize', updateWidth)
    return () => window.removeEventListener('resize', updateWidth)
  }, [accountType, token, apiUrl])

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!editMultiplier || !editDate) return

    try {
      const resp = await fetch(`${apiUrl}/settings/multipliers`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          account_type: accountType,
          multiplier: Number(editMultiplier),
          effective_date: editDate,
        }),
      })

      if (resp.ok) {
        setEditing(false)
        setEditMultiplier('')
        setEditDate('')
        await fetchHistory()
        if (onSaved) onSaved()
      } else {
        alert('Failed to update multiplier')
      }
    } catch (error) {
      console.error('Error updating multiplier:', error)
      alert('Failed to update multiplier')
    }
  }

  const handleNewEntry = () => {
    setEditingId(null)
    setEditMultiplier('')
    setEditDate(new Date().toISOString().split('T')[0])
    setEditing(true)
  }

  const handleEditEntry = (entry: MultiplierHistory) => {
    setEditingId(entry.id)
    setEditMultiplier(entry.multiplier.toString())
    setEditDate(entry.date)
    setEditing(true)
  }

  const handleDeleteEntry = async (entryId: number) => {
    if (!confirm('Are you sure you want to delete this multiplier history entry?')) {
      return
    }

    try {
      const resp = await fetch(`${apiUrl}/settings/multipliers/history/${entryId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      })

      if (resp.ok) {
        await fetchHistory()
        if (onSaved) onSaved()
      } else {
        alert('Failed to delete multiplier history entry')
      }
    } catch (error) {
      console.error('Error deleting multiplier history:', error)
      alert('Failed to delete multiplier history entry')
    }
  }

  if (loading) {
    return <div>Loading multiplier history...</div>
  }

  if (history.length === 0) {
    return (
      <div>
        <p>No multiplier history available.</p>
        <button onClick={handleNewEntry}>Add First Entry</button>
        {editing && (
          <form onSubmit={handleSubmit} style={{ marginTop: '1rem', padding: '1rem', border: '1px solid #ccc', borderRadius: '4px' }}>
            <label>
              Date:
              <input
                type="date"
                value={editDate}
                onChange={(e) => setEditDate(e.target.value)}
                required
                style={{ marginLeft: '0.5rem' }}
              />
            </label>
            <label style={{ marginLeft: '1rem' }}>
              Multiplier:
              <input
                type="number"
                step="0.01"
                min="0"
                value={editMultiplier}
                onChange={(e) => setEditMultiplier(e.target.value)}
                required
                style={{ marginLeft: '0.5rem' }}
              />
            </label>
            <button type="submit" style={{ marginLeft: '1rem' }}>Save</button>
            <button type="button" onClick={() => setEditing(false)} style={{ marginLeft: '0.5rem' }}>Cancel</button>
          </form>
        )}
      </div>
    )
  }

  // Calculate chart dimensions
  const padding = { top: 20, right: 40, bottom: 40, left: 60 }
  const chartAreaWidth = chartWidth - padding.left - padding.right
  const chartAreaHeight = chartHeight - padding.top - padding.bottom

  // Get date range
  const dates = history.map(h => new Date(h.date))
  const minDate = new Date(Math.min(...dates.map(d => d.getTime())))
  const maxDate = new Date(Math.max(...dates.map(d => d.getTime())))
  const dateRange = maxDate.getTime() - minDate.getTime() || 1

  // Get multiplier range
  const multipliers = history.map(h => h.multiplier)
  const minMultiplier = Math.min(...multipliers)
  const maxMultiplier = Math.max(...multipliers)
  const multiplierRange = maxMultiplier - minMultiplier || 1
  const multiplierPadding = multiplierRange * 0.1

  // Calculate points for step chart
  // Each point represents when a multiplier change occurs
  const points = history.map((h, pointIdx) => {
    const x = padding.left + ((new Date(h.date).getTime() - minDate.getTime()) / dateRange) * chartAreaWidth
    const y = padding.top + chartAreaHeight - (((h.multiplier - minMultiplier + multiplierPadding) / (multiplierRange + multiplierPadding * 2)) * chartAreaHeight)
    return { x, y, multiplier: h.multiplier, date: h.date, id: h.id, idx: pointIdx }
  })

  // Create step segments: horizontal lines extending from each point until the next point
  // Step chart: each multiplier stays flat (horizontal) until the next change
  const stepSegments: Array<{x1: number, y1: number, x2: number, y2: number, multiplier: number}> = []
  for (let i = 0; i < points.length; i++) {
    const currentPoint = points[i]
    if (i < points.length - 1) {
      // Draw horizontal line from this point to the x-position of the next point
      const nextPoint = points[i + 1]
      stepSegments.push({
        x1: currentPoint.x,
        y1: currentPoint.y,
        x2: nextPoint.x,
        y2: currentPoint.y, // Same y (horizontal line)
        multiplier: currentPoint.multiplier
      })
    } else {
      // Last point: extend to the right edge of the chart
      stepSegments.push({
        x1: currentPoint.x,
        y1: currentPoint.y,
        x2: chartWidth - padding.right,
        y2: currentPoint.y,
        multiplier: currentPoint.multiplier
      })
    }
  }
  
  // Also add vertical segments at each change point to show the step
  const verticalSegments: Array<{x: number, y1: number, y2: number}> = []
  for (let i = 1; i < points.length; i++) {
    const prevPoint = points[i - 1]
    const currentPoint = points[i]
    if (prevPoint.y !== currentPoint.y) {
      // Only draw vertical line if the multiplier actually changed
      verticalSegments.push({
        x: currentPoint.x,
        y1: prevPoint.y,
        y2: currentPoint.y
      })
    }
  }

  // Format date for display
  const formatDate = (dateStr: string) => {
    const d = new Date(dateStr)
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  }

  // Y-axis labels
  const yAxisSteps = 5
  const yAxisLabels = []
  for (let i = 0; i <= yAxisSteps; i++) {
    const value = minMultiplier - multiplierPadding + (multiplierRange + multiplierPadding * 2) * (i / yAxisSteps)
    const y = padding.top + chartAreaHeight - (chartAreaHeight * (i / yAxisSteps))
    yAxisLabels.push({ value, y })
  }

  return (
    <div id={`chart-container-${accountType}`} style={{ width: '100%', maxWidth: '100%', overflowX: 'auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <h3 style={{ margin: 0 }}>
          {accountType === 'savings' ? 'Savings' : 'College Savings'} Multiplier History
        </h3>
        <button onClick={handleNewEntry}>Add Entry</button>
      </div>

      {editing && (
        <form onSubmit={handleSubmit} style={{ marginBottom: '1rem', padding: '1rem', border: '1px solid #ccc', borderRadius: '4px', backgroundColor: '#f9f9f9' }}>
          <div style={{ marginBottom: '0.5rem' }}>
            {editingId ? <strong>Editing Entry</strong> : <strong>New Entry</strong>}
          </div>
          <label>
            Date:
            <input
              type="date"
              value={editDate}
              onChange={(e) => setEditDate(e.target.value)}
              required
              style={{ marginLeft: '0.5rem', marginRight: '1rem' }}
            />
          </label>
          <label>
            Multiplier:
            <input
              type="number"
              step="0.01"
              min="0"
              value={editMultiplier}
              onChange={(e) => setEditMultiplier(e.target.value)}
              required
              style={{ marginLeft: '0.5rem', marginRight: '1rem' }}
            />
          </label>
          <button type="submit">{editingId ? 'Update' : 'Save'}</button>
          <button type="button" onClick={() => {
            setEditing(false)
            setEditingId(null)
            setEditMultiplier('')
            setEditDate('')
          }} style={{ marginLeft: '0.5rem' }}>Cancel</button>
        </form>
      )}

      <div style={{ border: '1px solid #ccc', borderRadius: '4px', padding: '1rem', backgroundColor: '#fff' }}>
        <svg width={chartWidth} height={chartHeight} style={{ display: 'block' }}>
          {/* Grid lines */}
          {yAxisLabels.map((label, idx) => (
            <line
              key={idx}
              x1={padding.left}
              y1={label.y}
              x2={chartWidth - padding.right}
              y2={label.y}
              stroke="#e0e0e0"
              strokeWidth="1"
            />
          ))}

          {/* X-axis */}
          <line
            x1={padding.left}
            y1={chartHeight - padding.bottom}
            x2={chartWidth - padding.right}
            y2={chartHeight - padding.bottom}
            stroke="#333"
            strokeWidth="2"
          />

          {/* Y-axis */}
          <line
            x1={padding.left}
            y1={padding.top}
            x2={padding.left}
            y2={chartHeight - padding.bottom}
            stroke="#333"
            strokeWidth="2"
          />

          {/* Y-axis labels */}
          {yAxisLabels.map((label, idx) => (
            <text
              key={idx}
              x={padding.left - 10}
              y={label.y + 4}
              textAnchor="end"
              fontSize="12"
              fill="#666"
            >
              {label.value.toFixed(2)}x
            </text>
          ))}

          {/* X-axis date labels (show first, last, and a few in between) */}
          {points.map((point) => {
            if (point.idx === 0 || point.idx === points.length - 1 || point.idx % Math.max(1, Math.floor(points.length / 5)) === 0) {
              return (
                <g key={point.id}>
                  <line
                    x1={point.x}
                    y1={chartHeight - padding.bottom}
                    x2={point.x}
                    y2={chartHeight - padding.bottom + 5}
                    stroke="#333"
                    strokeWidth="1"
                  />
                  <text
                    x={point.x}
                    y={chartHeight - padding.bottom + 20}
                    textAnchor="middle"
                    fontSize="10"
                    fill="#666"
                    transform={`rotate(-45 ${point.x} ${chartHeight - padding.bottom + 20})`}
                  >
                    {formatDate(point.date)}
                  </text>
                </g>
              )
            }
            return null
          })}

          {/* Step chart: Horizontal segments (flat until next change) */}
          {stepSegments.map((segment, idx) => (
            <line
              key={`step-${idx}`}
              x1={segment.x1}
              y1={segment.y1}
              x2={segment.x2}
              y2={segment.y2}
              stroke="#4a90e2"
              strokeWidth="2"
            />
          ))}
          
          {/* Vertical segments at change points */}
          {verticalSegments.map((segment, idx) => (
            <line
              key={`vert-${idx}`}
              x1={segment.x}
              y1={segment.y1}
              x2={segment.x}
              y2={segment.y2}
              stroke="#4a90e2"
              strokeWidth="2"
            />
          ))}

          {/* Data points */}
          {points.map((point) => (
            <g key={point.id}>
              <circle
                cx={point.x}
                cy={point.y}
                r="4"
                fill="#4a90e2"
                stroke="#fff"
                strokeWidth="2"
              />
              <title>{formatDate(point.date)}: {point.multiplier.toFixed(2)}x</title>
            </g>
          ))}
        </svg>
      </div>

      {/* History table */}
      <div style={{ marginTop: '1rem' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.9em' }}>
          <thead>
            <tr style={{ borderBottom: '2px solid #ccc' }}>
              <th style={{ textAlign: 'left', padding: '0.5rem' }}>Date</th>
              <th style={{ textAlign: 'right', padding: '0.5rem' }}>Multiplier</th>
              <th style={{ textAlign: 'left', padding: '0.5rem' }}>Created At</th>
              <th style={{ textAlign: 'center', padding: '0.5rem' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {[...history].reverse().map((entry) => (
              <tr 
                key={entry.id} 
                style={{ 
                  borderBottom: '1px solid #eee',
                  cursor: 'pointer',
                  backgroundColor: editingId === entry.id ? '#f0f8ff' : 'transparent'
                }}
                onClick={() => handleEditEntry(entry)}
              >
                <td style={{ padding: '0.5rem' }}>{formatDate(entry.date)}</td>
                <td style={{ textAlign: 'right', padding: '0.5rem' }}>{entry.multiplier.toFixed(2)}x</td>
                <td style={{ padding: '0.5rem', color: '#666', fontSize: '0.85em' }}>
                  {new Date(entry.created_at).toLocaleString()}
                </td>
                <td style={{ textAlign: 'center', padding: '0.5rem' }} onClick={(e) => e.stopPropagation()}>
                  <button
                    onClick={() => handleDeleteEntry(entry.id)}
                    style={{
                      padding: '0.25rem 0.5rem',
                      fontSize: '0.85em',
                      backgroundColor: '#dc3545',
                      color: 'white',
                      border: 'none',
                      borderRadius: '3px',
                      cursor: 'pointer'
                    }}
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}


import { NavLink } from 'react-router-dom'
import './Header.css'
import Logo from './Logo'

interface Props {
  onLogout: () => void
  isAdmin: boolean
  isChild: boolean
  siteName: string
  onToggleTheme: () => void
  theme: 'light' | 'dark'
  choresUiEnabled: boolean
  loansUiEnabled: boolean
  couponsUiEnabled: boolean
  messagesUiEnabled: boolean
}

export default function Header({ onLogout, isAdmin, isChild, siteName, onToggleTheme, theme, choresUiEnabled, loansUiEnabled, couponsUiEnabled, messagesUiEnabled }: Props) {
  return (
    <header className="header">
      <Logo alt={`${siteName} Logo`} className="logo" transparent={true} />
      <nav aria-label="Main navigation">
        <ul>
          {isChild ? (
              <>
                <li><NavLink to="/child" className={({isActive}) => isActive ? 'active' : undefined}>Ledger</NavLink></li>
                {loansUiEnabled && <li><NavLink to="/child/loans" className={({isActive}) => isActive ? 'active' : undefined}>Loans</NavLink></li>}
                {choresUiEnabled && <li><NavLink to="/child/chores" className={({isActive}) => isActive ? 'active' : undefined}>Chores</NavLink></li>}
                {couponsUiEnabled && <li><NavLink to="/child/coupons" className={({isActive}) => isActive ? 'active' : undefined}>Coupons</NavLink></li>}
                <li><NavLink to="/child/bank101" className={({isActive}) => isActive ? 'active' : undefined}>Bank 101</NavLink></li>
                {messagesUiEnabled && <li><NavLink to="/child/messages" className={({isActive}) => isActive ? 'active' : undefined}>Messages</NavLink></li>}
                <li><NavLink to="/child/profile" className={({isActive}) => isActive ? 'active' : undefined}>Profile</NavLink></li>
              </>
            ) : (
              <>
                <li><NavLink to="/" className={({isActive}) => isActive ? 'active' : undefined}>Dashboard</NavLink></li>
                <li><NavLink to="/parent/chores" className={({isActive}) => isActive ? 'active' : undefined}>Chores</NavLink></li>
                <li><NavLink to="/parent/loans" className={({isActive}) => isActive ? 'active' : undefined}>Loans</NavLink></li>
                <li><NavLink to="/parent/coupons" className={({isActive}) => isActive ? 'active' : undefined}>Coupons</NavLink></li>
                <li><NavLink to="/messages" className={({isActive}) => isActive ? 'active' : undefined}>Messages</NavLink></li>
                <li><NavLink to="/parent/profile" className={({isActive}) => isActive ? 'active' : undefined}>Profile</NavLink></li>
              </>
            )}
          {isAdmin && (
            <>
              <li><NavLink to="/admin" className={({isActive}) => isActive ? 'active' : undefined}>Admin</NavLink></li>
              <li><NavLink to="/admin/coupons" className={({isActive}) => isActive ? 'active' : undefined}>Admin Coupons</NavLink></li>
            </>
          )}
          <li>
            <button
              onClick={onToggleTheme}
              aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
            >
              {theme === 'dark' ? 'Light Mode' : 'Dark Mode'}
            </button>
          </li>
          <li><button onClick={onLogout}>Logout</button></li>
        </ul>
      </nav>
    </header>
  )
}

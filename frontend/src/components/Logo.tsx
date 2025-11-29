import { useState } from 'react'
import { getLogoPaths } from '../utils/logo'

interface LogoProps {
  alt: string
  className?: string
  transparent?: boolean
}

/**
 * Logo component with automatic fallback to default logo if custom logo is not found.
 */
export default function Logo({ alt, className, transparent = false }: LogoProps) {
  const logoPaths = transparent 
    ? { primary: '/bank-logo-trans.png', fallback: '/uncle-jon-trans.png' }
    : getLogoPaths()
  
  const [logoPath, setLogoPath] = useState(logoPaths.primary)
  const [hasError, setHasError] = useState(false)

  const handleError = () => {
    if (!hasError) {
      setHasError(true)
      setLogoPath(logoPaths.fallback)
    }
  }

  return (
    <img 
      src={logoPath} 
      alt={alt} 
      className={className}
      onError={handleError}
    />
  )
}


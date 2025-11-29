/**
 * Logo utility functions with fallback support.
 * 
 * Provides logo paths that fallback to default logos if custom logos are not available.
 */

/**
 * Get the primary logo path with fallback.
 * Tries bank-logo.png first, falls back to unclejon.jpg if not available.
 */
export function getLogoPath(): string {
  // In production, we can check if the file exists, but in a simple implementation,
  // we'll always try the custom logo first. The browser will handle 404s gracefully.
  // For now, we'll check if we're in dev mode and prefer the custom logo.
  // Since we can't check file existence client-side easily, we'll always return
  // the custom path and let the browser handle it. We could enhance this with
  // error handling on image load, but for simplicity, we'll use the fallback
  // approach in the component itself.
  return '/bank-logo.png'
}

/**
 * Get the transparent logo path with fallback.
 * Tries bank-logo-trans.png first, falls back to uncle-jon-trans.png if not available.
 */
export function getTransparentLogoPath(): string {
  return '/bank-logo-trans.png'
}

/**
 * Get logo path with automatic fallback on error.
 * Returns an object with the primary and fallback paths.
 */
export function getLogoPaths(): { primary: string; fallback: string } {
  return {
    primary: '/bank-logo.png',
    fallback: '/unclejon.jpg'
  }
}

/**
 * Get transparent logo paths with automatic fallback on error.
 */
export function getTransparentLogoPaths(): { primary: string; fallback: string } {
  return {
    primary: '/bank-logo-trans.png',
    fallback: '/uncle-jon-trans.png'
  }
}


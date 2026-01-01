/**
 * Admin Mode Framework
 * 
 * Centralized admin mode checks. Currently uses dev mode (localStorage),
 * but designed to be easily swapped for real authentication/roles later.
 */

const DEV_MODE_KEY = "dashboard_dev_mode";

/**
 * Check if dev mode is enabled (reads from localStorage)
 */
export function isDevMode(): boolean {
  if (typeof window === "undefined") return false;
  const devMode = localStorage.getItem(DEV_MODE_KEY);
  return devMode === "true";
}

/**
 * Check if admin mode is enabled.
 * For now, same as dev mode, but future-ready for real auth.
 */
export function isAdminMode(): boolean {
  // TODO: Later, check for real admin role/permissions here
  // For now, use dev mode as the gate
  return isDevMode();
}

/**
 * Require admin mode - throws error if not in admin mode.
 * Use this for critical operations that must have admin access.
 */
export function requireAdminMode(): void {
  if (!isAdminMode()) {
    throw new Error("Admin mode required");
  }
}

/**
 * Get admin mode status (for debugging/logging)
 */
export function getAdminModeStatus(): { isAdmin: boolean; isDev: boolean } {
  return {
    isAdmin: isAdminMode(),
    isDev: isDevMode(),
  };
}



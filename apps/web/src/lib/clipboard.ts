/**
 * Copies text, resolving to whether it worked. The async Clipboard API needs
 * a secure context (and may be denied); the fallback copies a selected,
 * off-screen textarea, which also works on plain-http LAN previews.
 */
export async function copyText(text: string): Promise<boolean> {
  if (window.isSecureContext && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Permission denied or no focus: try the legacy path below.
    }
  }
  return legacyCopy(text);
}

function legacyCopy(text: string): boolean {
  const focused =
    document.activeElement instanceof HTMLElement
      ? document.activeElement
      : undefined;
  const area = document.createElement('textarea');
  area.value = text;
  area.setAttribute('readonly', '');
  area.setAttribute('aria-hidden', 'true');
  area.style.cssText = 'position:fixed;top:0;left:0;opacity:0;';
  document.body.append(area);
  area.select();
  let copied = false;
  try {
    copied = document.execCommand('copy');
  } catch {
    copied = false;
  }
  area.remove();
  focused?.focus({ preventScroll: true });
  return copied;
}

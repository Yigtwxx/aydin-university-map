import { afterEach, describe, expect, it, vi } from 'vitest';

import { copyText } from './clipboard';

function stubClipboard(writeText?: (text: string) => Promise<void>) {
  vi.stubGlobal('isSecureContext', true);
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: writeText ? { writeText } : undefined,
  });
}

function stubExecCommand(result: boolean) {
  const execCommand = vi.fn(() => result);
  Object.defineProperty(document, 'execCommand', {
    configurable: true,
    value: execCommand,
  });
  return execCommand;
}

afterEach(() => {
  vi.unstubAllGlobals();
  Reflect.deleteProperty(navigator, 'clipboard');
  Reflect.deleteProperty(document, 'execCommand');
});

describe('copyText', () => {
  it('uses the Clipboard API when it is available', async () => {
    const writeText = vi.fn(() => Promise.resolve());
    stubClipboard(writeText);
    const execCommand = stubExecCommand(true);
    await expect(copyText('https://x/tr/map?to=a')).resolves.toBe(true);
    expect(writeText).toHaveBeenCalledWith('https://x/tr/map?to=a');
    expect(execCommand).not.toHaveBeenCalled();
  });

  it('falls back to a selected textarea when the API is refused', async () => {
    stubClipboard(() => Promise.reject(new Error('denied')));
    const execCommand = stubExecCommand(true);
    const button = document.createElement('button');
    document.body.append(button);
    button.focus();
    await expect(copyText('link')).resolves.toBe(true);
    expect(execCommand).toHaveBeenCalledWith('copy');
    // The temporary field is gone and focus is back where it was.
    expect(document.querySelector('textarea')).toBeNull();
    expect(document.activeElement).toBe(button);
    button.remove();
  });

  it('reports failure when neither path copies', async () => {
    stubClipboard(undefined);
    stubExecCommand(false);
    await expect(copyText('link')).resolves.toBe(false);
  });
});

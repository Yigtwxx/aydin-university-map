import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { RichText } from './RichText';

describe('RichText', () => {
  it('renders bold and lists without raw markdown', () => {
    const { container } = render(
      <RichText text={'Rota **1 dk** sürer.\n- Düz yürüyün\n- Sola dönün'} />,
    );
    expect(container.querySelector('strong')?.textContent).toBe('1 dk');
    expect(container.querySelectorAll('li')).toHaveLength(2);
    expect(container.textContent).not.toContain('**');
  });

  it('never injects HTML from the text', () => {
    const { container } = render(
      <RichText text="<img src=x onerror=alert(1)>" />,
    );
    expect(container.querySelector('img')).toBeNull();
  });
});

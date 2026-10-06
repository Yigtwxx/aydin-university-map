import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { linkify, RichText } from './RichText';

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

  it('turns addresses into links that open safely in a new tab', () => {
    const { container } = render(
      <RichText
        text="Ayrıntılar https://www.aydin.edu.tr/tr-tr/kutuphane adresinde."
        newTab="(yeni sekmede açılır)"
      />,
    );
    const link = container.querySelector('a');
    expect(link?.getAttribute('href')).toBe(
      'https://www.aydin.edu.tr/tr-tr/kutuphane',
    );
    expect(link?.getAttribute('target')).toBe('_blank');
    expect(link?.getAttribute('rel')).toContain('noopener');
    // Shown without the scheme; the sentence's full stop stays text.
    expect(link?.textContent).toBe(
      'aydin.edu.tr/tr-tr/kutuphane (yeni sekmede açılır)',
    );
    expect(container.textContent).toMatch(/adresinde\.$/);
  });

  it('links inside bold text too', () => {
    const { container } = render(<RichText text="**aydin.edu.tr**" />);
    expect(container.querySelector('strong a')?.getAttribute('href')).toBe(
      'https://aydin.edu.tr',
    );
  });
});

describe('linkify', () => {
  it('finds bare university addresses and stops at a Turkish suffix', () => {
    expect(
      linkify('Duyurular aydin.edu.tr’den, kayıt ogrenci.aydin.edu.tr'),
    ).toEqual([
      'Duyurular ',
      { href: 'https://aydin.edu.tr', text: 'aydin.edu.tr' },
      '’den, kayıt ',
      { href: 'https://ogrenci.aydin.edu.tr', text: 'ogrenci.aydin.edu.tr' },
    ]);
  });

  it('reads e-mail addresses as mail links, not as hosts', () => {
    expect(linkify('Yazın: info@aydin.edu.tr.')).toEqual([
      'Yazın: ',
      { href: 'mailto:info@aydin.edu.tr', text: 'info@aydin.edu.tr' },
      '.',
    ]);
  });

  it('keeps closing brackets and other schemes out', () => {
    expect(linkify('(bkz. https://example.org/a)')).toEqual([
      '(bkz. ',
      { href: 'https://example.org/a', text: 'example.org/a' },
      ')',
    ]);
    expect(linkify('javascript:alert(1) and ftp://x.y')).toEqual([
      'javascript:alert(1) and ftp://x.y',
    ]);
  });

  it('leaves text without addresses alone', () => {
    expect(linkify('E Blok girişi, 2. kat.')).toEqual([
      'E Blok girişi, 2. kat.',
    ]);
  });
});

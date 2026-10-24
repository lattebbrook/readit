import { describe, expect, it } from 'vitest';
import { formatCount, formatScore, pickTextColor, relativeTime, renderBody } from '../lib/format';

describe('formatScore', () => {
  it('leaves small numbers alone', () => {
    expect(formatScore(0)).toBe('0');
    expect(formatScore(999)).toBe('999');
    expect(formatScore(-42)).toBe('-42');
  });

  it('abbreviates thousands and millions', () => {
    expect(formatScore(1200)).toBe('1.2k');
    expect(formatScore(45_000)).toBe('45k');
    expect(formatScore(2_400_000)).toBe('2.4m');
  });

  it('abbreviates negative magnitudes too', () => {
    expect(formatScore(-1200)).toBe('-1.2k');
  });
});

describe('formatCount', () => {
  it('pluralises', () => {
    expect(formatCount(1, 'comment')).toBe('1 comment');
    expect(formatCount(2, 'comment')).toBe('2 comments');
    expect(formatCount(3, 'reply', 'replies')).toBe('3 replies');
  });
});

describe('relativeTime', () => {
  const now = () => Date.now() / 1000;

  it('describes recent times', () => {
    expect(relativeTime(now())).toBe('just now');
    expect(relativeTime(now() - 300)).toBe('5m ago');
    expect(relativeTime(now() - 7200)).toBe('2h ago');
    expect(relativeTime(now() - 86_400 * 3)).toBe('3d ago');
    expect(relativeTime(now() - 86_400 * 400)).toBe('1y ago');
  });

  it('never reports negative time for clock skew', () => {
    expect(relativeTime(now() + 600)).toBe('just now');
  });
});

describe('renderBody', () => {
  it('escapes HTML so model and user text cannot inject markup', () => {
    const html = renderBody('<script>alert(1)</script>');
    expect(html).not.toContain('<script>');
    expect(html).toContain('&lt;script&gt;');
  });

  it('escapes attribute-breaking quotes', () => {
    expect(renderBody('say "hi"')).toContain('&quot;hi&quot;');
  });

  it('renders quote blocks', () => {
    const html = renderBody('> you said this\nand I disagree');
    expect(html).toContain('<blockquote>');
    expect(html).toContain('you said this');
    expect(html).toContain('</blockquote>');
  });

  it('renders inline emphasis and code', () => {
    const html = renderBody('**bold** and *italic* and `code` and ~~gone~~');
    expect(html).toContain('<strong>bold</strong>');
    expect(html).toContain('<em>italic</em>');
    expect(html).toContain('<code>code</code>');
    expect(html).toContain('<del>gone</del>');
  });

  it('linkifies urls with safe rel attributes', () => {
    const html = renderBody('see https://example.com/x');
    expect(html).toContain('href="https://example.com/x"');
    expect(html).toContain('rel="noopener noreferrer"');
  });

  it('linkifies board and user handles', () => {
    const html = renderBody('go to r/funny and ask u/someone');
    expect(html).toContain('href="/r/funny"');
    expect(html).toContain('href="/u/someone"');
  });

  it('does not linkify a javascript scheme', () => {
    expect(renderBody('javascript:alert(1)')).not.toContain('href="javascript:');
  });

  it('handles empty input', () => {
    expect(renderBody('')).toBe('');
  });
});

describe('pickTextColor', () => {
  it('picks readable foregrounds', () => {
    expect(pickTextColor('#ffffff')).toBe('#111111');
    expect(pickTextColor('#000000')).toBe('#ffffff');
    expect(pickTextColor('nonsense')).toBe('#ffffff');
  });
});

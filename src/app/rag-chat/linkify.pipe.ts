import { Pipe, PipeTransform, inject } from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';

/**
 * Escapes HTML in a string, then turns bare http(s) URLs into clickable links
 * that open in a new tab. Escaping first keeps LLM output safe (no injection);
 * only matched URLs become anchors.
 */
@Pipe({ name: 'linkify' })
export class LinkifyPipe implements PipeTransform {
  private readonly sanitizer = inject(DomSanitizer);

  transform(value: string | null | undefined): SafeHtml {
    const escaped = (value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');

    const linked = escaped.replace(/(https?:\/\/[^\s<]+)/g, (match) => {
      const url = match.replace(/[.,;:!?)\]]+$/, ''); // drop trailing punctuation
      const trailing = match.slice(url.length);
      return `<a href="${url}" target="_blank" rel="noopener">${url}</a>${trailing}`;
    });

    return this.sanitizer.bypassSecurityTrustHtml(linked);
  }
}

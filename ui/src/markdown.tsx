// A deliberately small Markdown subset rendered to React elements, never to
// innerHTML, so canvas text can't inject markup or script.
import type { ReactNode } from "react";

export function safeUrl(url: string): string | undefined {
  try {
    const u = new URL(url);
    return u.protocol === "http:" || u.protocol === "https:" ? u.href : undefined;
  } catch {
    return undefined;
  }
}

const INLINE = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\)|\[\[[^\]]+\]\])/;

function inline(text: string, key: string): ReactNode[] {
  return text.split(INLINE).map((part, i) => {
    const k = `${key}-${i}`;
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) return <strong key={k}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) return <code key={k}>{part.slice(1, -1)}</code>;
    if (part.startsWith("[[") && part.endsWith("]]")) return <span key={k} className="wikilink">{part.slice(2, -2)}</span>;
    const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(part);
    if (link) {
      const href = safeUrl(link[2]);
      return href ? (
        <a key={k} href={href} target="_blank" rel="noopener noreferrer" className="nodrag">{link[1]}</a>
      ) : (
        <span key={k}>{link[1]}</span>
      );
    }
    if (part.startsWith("*") && part.endsWith("*") && part.length > 2) return <em key={k}>{part.slice(1, -1)}</em>;
    return part;
  });
}

export function Markdown({ text }: { text: string }) {
  const out: ReactNode[] = [];
  let list: ReactNode[] = [];
  const flush = () => {
    if (list.length) out.push(<ul key={`ul${out.length}`}>{list}</ul>);
    list = [];
  };
  text.split("\n").forEach((line, i) => {
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    const li = /^\s*[-*+]\s+(.*)$/.exec(line);
    if (li) {
      list.push(<li key={i}>{inline(li[1], `l${i}`)}</li>);
      return;
    }
    flush();
    if (h) {
      const Tag = `h${h[1].length}` as "h1";
      out.push(<Tag key={i}>{inline(h[2], `h${i}`)}</Tag>);
    } else if (line.trim() === "") {
      out.push(<div key={i} className="md-gap" />);
    } else {
      out.push(<p key={i}>{inline(line, `p${i}`)}</p>);
    }
  });
  flush();
  return <div className="md">{out}</div>;
}

interface FilePathTextProps {
  text: string;
  onPathClick?: (path: string) => void;
  className?: string;
  pathClassName?: string;
}

type Segment =
  | { type: 'text'; value: string }
  | { type: 'path'; value: string };

const FILE_PATH_REGEX = /([A-Za-z]:[\\/][^\s"'`()[\]<>]+|\/[^\s"'`()[\]<>]+|(?:\.{1,2}[\\/]|[A-Za-z_.-][A-Za-z0-9_.-]*[\\/])[^\s"'`()[\]<>]+)/g;
const LEADING_WRAP_REGEX = /^[("'[{<]+/;
const TRAILING_WRAP_REGEX = /[),\].!?'"}>]+$/;

function splitIntoSegments(text: string): Segment[] {
  const segments: Segment[] = [];
  let lastIndex = 0;

  for (const match of text.matchAll(FILE_PATH_REGEX)) {
    const rawMatch = match[0];
    const start = match.index ?? 0;
    const end = start + rawMatch.length;
    const protocolProbe = text.slice(Math.max(0, start - 8), start);

    if (rawMatch.startsWith('/') && /https?:$/i.test(protocolProbe)) {
      segments.push({ type: 'text', value: text.slice(lastIndex, end) });
      lastIndex = end;
      continue;
    }

    const leadingWrap = rawMatch.match(LEADING_WRAP_REGEX)?.[0] ?? '';
    const trailingWrap = rawMatch.match(TRAILING_WRAP_REGEX)?.[0] ?? '';
    const pathValue = rawMatch.slice(leadingWrap.length, rawMatch.length - trailingWrap.length);

    if (start > lastIndex) {
      segments.push({ type: 'text', value: text.slice(lastIndex, start) + leadingWrap });
    } else if (leadingWrap) {
      segments.push({ type: 'text', value: leadingWrap });
    }

    if (pathValue) {
      segments.push({ type: 'path', value: pathValue });
    }

    if (trailingWrap) {
      segments.push({ type: 'text', value: trailingWrap });
    }

    lastIndex = end;
  }

  if (lastIndex < text.length) {
    segments.push({ type: 'text', value: text.slice(lastIndex) });
  }

  return segments;
}

function renderPlainText(text: string, keyPrefix: string) {
  return text.split('\n').map((line, index, lines) => (
    <span key={`${keyPrefix}-${index}`}>
      {line}
      {index < lines.length - 1 ? <br /> : null}
    </span>
  ));
}

export default function FilePathText({
  text,
  onPathClick,
  className = '',
  pathClassName = '',
}: FilePathTextProps) {
  const segments = splitIntoSegments(text);

  return (
    <span className={className}>
      {segments.map((segment, index) => {
        if (segment.type === 'text') {
          return renderPlainText(segment.value, `text-${index}`);
        }

        if (!onPathClick) {
          return <span key={`path-${index}`}>{segment.value}</span>;
        }

        return (
          <button
            key={`path-${index}`}
            type="button"
            onClick={() => onPathClick(segment.value)}
            className={`inline cursor-pointer rounded border-0 bg-transparent px-0.5 font-mono underline decoration-dotted underline-offset-2 transition hover:bg-white/10 hover:text-white ${pathClassName}`.trim()}
            title={`Open preview: ${segment.value}`}
          >
            {segment.value}
          </button>
        );
      })}
    </span>
  );
}

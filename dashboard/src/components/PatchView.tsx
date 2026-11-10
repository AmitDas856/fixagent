function lineClass(line: string): string {
  if (line.startsWith("+++") || line.startsWith("---")) return "diff-file";
  if (line.startsWith("@@")) return "diff-hunk";
  if (line.startsWith("+")) return "diff-add";
  if (line.startsWith("-")) return "diff-del";
  return "diff-context";
}

export default function PatchView({ patch }: { patch: string }) {
  const lines = patch.replace(/\n$/, "").split("\n");
  return (
    <pre className="patch" aria-label="Patch">
      {lines.map((line, index) => (
        <span key={index} className={lineClass(line)}>
          {line || " "}
          {"\n"}
        </span>
      ))}
    </pre>
  );
}

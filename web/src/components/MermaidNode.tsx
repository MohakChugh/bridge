import { Node, mergeAttributes } from "@tiptap/core";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import mermaid from "mermaid";

mermaid.initialize({
  startOnLoad: false,
  theme: "dark",
  securityLevel: "strict",
  fontFamily: "ui-monospace, monospace",
});

let mermaidCounter = 0;

async function renderMermaid(container: HTMLElement, code: string) {
  if (!code.trim()) return;
  const id = `mermaid-deco-${mermaidCounter++}`;
  try {
    const { svg } = await mermaid.render(id, code.trim());
    const parser = new DOMParser();
    const doc = parser.parseFromString(svg, "image/svg+xml");
    const svgEl = doc.documentElement;
    container.replaceChildren(svgEl);
    container.classList.remove("mermaid-error");
  } catch (err: any) {
    container.textContent = `Mermaid error: ${err?.message || "render failed"}`;
    container.classList.add("mermaid-error");
    document.getElementById(id)?.remove();
  }
}

const mermaidPluginKey = new PluginKey("mermaidPreview");

export const MermaidPreviewPlugin = new Plugin({
  key: mermaidPluginKey,
  state: {
    init() { return DecorationSet.empty; },
    apply(tr, oldSet, oldState, newState) {
      const decorations: Decoration[] = [];
      newState.doc.descendants((node, pos) => {
        if (node.type.name === "codeBlock" && node.attrs.language === "mermaid") {
          const code = node.textContent;
          const widget = Decoration.widget(pos + node.nodeSize, (view) => {
            const container = document.createElement("div");
            container.className = "mermaid-preview-container";
            renderMermaid(container, code);
            return container;
          }, { side: 1, key: `mermaid-${pos}-${code.length}` });
          decorations.push(widget);
        }
      });
      return DecorationSet.create(newState.doc, decorations);
    },
  },
  props: {
    decorations(state) {
      return mermaidPluginKey.getState(state);
    },
  },
});

export const MermaidExtension = Node.create({
  name: "mermaidExtension",

  addProseMirrorPlugins() {
    return [MermaidPreviewPlugin];
  },
});

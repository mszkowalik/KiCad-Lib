import { useEffect, useMemo, useState } from "react";
import {
  createCategory,
  deleteCategory,
  errorMessage,
  updateCategory,
  type CategoryNode,
} from "../api";

interface Props {
  tree: CategoryNode[];
  selectedId: number | null;
  onSelect: (id: number | null) => void;
  /** Called after any category create/rename/delete so the owner refetches. */
  onChanged?: () => void;
}

/** ids of every ancestor of `id` (not including `id` itself). */
function ancestorIds(tree: CategoryNode[], id: number): number[] {
  const path: number[] = [];
  const walk = (nodes: CategoryNode[], trail: number[]): boolean => {
    for (const n of nodes) {
      if (n.id === id) {
        path.push(...trail);
        return true;
      }
      if (n.children.length > 0 && walk(n.children, [...trail, n.id])) return true;
    }
    return false;
  };
  walk(tree, []);
  return path;
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      className={"chev" + (open ? " open" : "")}
      width="10"
      height="10"
      viewBox="0 0 10 10"
      aria-hidden="true"
    >
      <path d="M3 1.5 L7 5 L3 8.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

interface ManageOps {
  addChild: (parent: CategoryNode | null) => void;
  rename: (node: CategoryNode) => void;
  remove: (node: CategoryNode) => void;
}

function TreeNode({
  node,
  depth,
  selectedId,
  expanded,
  onSelect,
  onToggle,
  manage,
  ops,
}: {
  node: CategoryNode;
  depth: number;
  selectedId: number | null;
  expanded: Set<number>;
  onSelect: (id: number | null) => void;
  onToggle: (id: number) => void;
  manage: boolean;
  ops: ManageOps;
}) {
  const isOpen = expanded.has(node.id);
  const hasKids = node.children.length > 0;
  return (
    <li>
      <div
        className={"cat-row" + (selectedId === node.id ? " selected" : "")}
        style={{ paddingLeft: `${depth * 14}px` }}
      >
        {hasKids ? (
          <button
            type="button"
            className="cat-caret"
            aria-label={isOpen ? `Collapse ${node.name}` : `Expand ${node.name}`}
            aria-expanded={isOpen}
            onClick={() => onToggle(node.id)}
          >
            <Chevron open={isOpen} />
          </button>
        ) : (
          <span className="cat-caret-spacer" aria-hidden="true" />
        )}
        <button
          type="button"
          className="cat-label"
          onClick={() => onSelect(node.id)}
          title={
            node.component_count !== node.total_count
              ? `${node.component_count} direct, ${node.total_count} incl. subcategories`
              : `${node.component_count} components`
          }
        >
          <span className="cat-name">{node.name}</span>
          {!manage ? <span className="cat-count">{node.total_count}</span> : null}
        </button>
        {manage ? (
          <span className="cat-actions">
            <button
              type="button"
              className="cat-act"
              title={`Add subcategory under ${node.name}`}
              onClick={() => ops.addChild(node)}
            >
              ＋
            </button>
            <button
              type="button"
              className="cat-act"
              title={`Rename ${node.name}`}
              onClick={() => ops.rename(node)}
            >
              ✎
            </button>
            <button
              type="button"
              className="cat-act cat-act-del"
              title={`Delete ${node.name}`}
              onClick={() => ops.remove(node)}
            >
              ✕
            </button>
          </span>
        ) : null}
      </div>
      {hasKids && isOpen ? (
        <ul className="cat-children">
          {node.children.map((child) => (
            <TreeNode
              key={child.id}
              node={child}
              depth={depth + 1}
              selectedId={selectedId}
              expanded={expanded}
              onSelect={onSelect}
              onToggle={onToggle}
              manage={manage}
              ops={ops}
            />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export default function CategoryTree({ tree, selectedId, onSelect, onChanged }: Props) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [manage, setManage] = useState(false);
  const [opError, setOpError] = useState<string | null>(null);

  // Make sure the path to the selected category is visible (e.g. deep link).
  useEffect(() => {
    if (selectedId == null) return;
    const ancestors = ancestorIds(tree, selectedId);
    if (ancestors.length === 0) return;
    setExpanded((prev) => {
      if (ancestors.every((id) => prev.has(id))) return prev;
      const next = new Set(prev);
      ancestors.forEach((id) => next.add(id));
      return next;
    });
  }, [tree, selectedId]);

  const grandTotal = useMemo(() => tree.reduce((sum, n) => sum + n.total_count, 0), [tree]);

  const toggle = (id: number) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const run = (op: Promise<unknown>, expandId?: number) => {
    setOpError(null);
    op.then(() => {
      if (expandId != null) setExpanded((prev) => new Set(prev).add(expandId));
      onChanged?.();
    }).catch((err) => setOpError(errorMessage(err)));
  };

  const ops: ManageOps = {
    addChild: (parent) => {
      const name = window.prompt(
        parent ? `New subcategory under "${parent.name}":` : "New top-level category:",
      );
      if (!name || !name.trim()) return;
      run(createCategory(name.trim(), parent ? parent.id : null), parent?.id);
    },
    rename: (node) => {
      const name = window.prompt(`Rename "${node.name}" to:`, node.name);
      if (!name || !name.trim() || name.trim() === node.name) return;
      run(updateCategory(node.id, { name: name.trim() }));
    },
    remove: (node) => {
      if (!window.confirm(`Delete category "${node.name}"?`)) return;
      run(deleteCategory(node.id));
    },
  };

  return (
    <nav className="cat-tree" aria-label="Categories">
      <div className="cat-head">
        <div className={"cat-row cat-all" + (selectedId === null ? " selected" : "")}>
          <span className="cat-caret-spacer" aria-hidden="true" />
          <button type="button" className="cat-label" onClick={() => onSelect(null)}>
            <span className="cat-name">All components</span>
            <span className="cat-count">{grandTotal}</span>
          </button>
          <button
            type="button"
            className={"cat-gear" + (manage ? " on" : "")}
            title={manage ? "Done managing categories" : "Manage categories"}
            aria-pressed={manage}
            onClick={() => {
              setManage((m) => !m);
              setOpError(null);
            }}
          >
            ⚙
          </button>
        </div>
      </div>
      <ul className="cat-children cat-root">
        {tree.map((node) => (
          <TreeNode
            key={node.id}
            node={node}
            depth={0}
            selectedId={selectedId}
            expanded={expanded}
            onSelect={onSelect}
            onToggle={toggle}
            manage={manage}
            ops={ops}
          />
        ))}
      </ul>
      {manage ? (
        <button type="button" className="btn btn-sm cat-add-root" onClick={() => ops.addChild(null)}>
          ＋ New top-level category
        </button>
      ) : null}
      {opError ? <div className="cat-error">{opError}</div> : null}
    </nav>
  );
}

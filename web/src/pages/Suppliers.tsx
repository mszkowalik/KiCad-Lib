/** Stock → Suppliers: the register (decision 0055). Its order prices every BOM. */
import SuppliersCard from "../components/SuppliersCard";
import PageShell from "../components/PageShell";

export default function Suppliers() {
  return (
    <PageShell>
      <div className="toolbar">
        <h1>Suppliers</h1>
        <span className="toolbar-total">Where parts are bought. The order picks every BOM price.</span>
      </div>
      <SuppliersCard />
    </PageShell>
  );
}

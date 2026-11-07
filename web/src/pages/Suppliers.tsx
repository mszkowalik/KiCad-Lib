/** Stock → Suppliers: the register (decision 0055). Its order prices every BOM. */
import SuppliersCard from "../components/SuppliersCard";

export default function Suppliers() {
  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <h1>Suppliers</h1>
          <span className="toolbar-total">Where parts are bought. The order picks every BOM price.</span>
        </div>
        <SuppliersCard />
      </div>
    </div>
  );
}

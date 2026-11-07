/** Finance → Exchange rates. Reading is open to everybody, because "no exchange
 *  rate for HUF" is a warning a non-admin meets and has to be able to look up. */
import FxRatesCard from "../components/FxRatesCard";

export default function ExchangeRates() {
  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <h1>Exchange rates</h1>
          <span className="toolbar-total">What every document is converted to USD with.</span>
        </div>
        <FxRatesCard />
      </div>
    </div>
  );
}

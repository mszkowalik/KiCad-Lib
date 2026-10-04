"""Reading the companies' invoices from KSeF, the national e-invoice system
(decision 0067). Read only: nothing here sends an invoice.

* `client` — KSeF API 2.0: authentication with a company's token, the
  metadata query, the invoice XML. Ported from 7Sigma's script.
* `parse` — an FA(3) XML into the platform's invoice document.
* `sync` — fetch a company's sales and purchase invoices into the inbox,
  link a sales invoice to the platform's draft of it, and import a purchase
  as a supplier document when a person or an agent says so. Fetching never
  writes money.
"""

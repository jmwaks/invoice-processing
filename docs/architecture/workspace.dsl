workspace "Acme AP — Invoice Processing" "C4 model for the invoice-processing prototype. See docs/architecture/README.md for how to view." {

    model {
        apOperator = person "AP Operator" "Drags invoices into the UI, reviews case files, retries with edits."

        acmeAp = softwareSystem "Acme AP — Invoice Processing" "Ingests invoices in six formats, validates against inventory, runs propose/critique/finalize approval, pays or logs." {
            // containers added in Task 2
        }

        // external systems added in Task 2
        // relationships added in Task 3
    }

    views {
        // views added in Task 5
        theme default
    }
}

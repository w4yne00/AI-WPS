(function () {
  function getActiveDocument() {
    if (window.wps && window.wps.ActiveDocument) {
      return window.wps.ActiveDocument;
    }
    return null;
  }

  function collectParagraphs(document) {
    var paragraphs = (document && (document.Paragraphs || document.paragraphs)) || [];
    var count = 0;
    var headingCount = 0;

    for (var i = 0; i < paragraphs.length; i += 1) {
      count += 1;
      var paragraphFormat = paragraphs[i].ParagraphFormat || {};
      var outlineLevel = paragraphFormat.OutlineLevel || 0;
      if (outlineLevel > 0) {
        headingCount += 1;
      }
    }

    return {
      paragraphCount: count,
      headingCount: headingCount
    };
  }

  function formatLines(result) {
    return [
      "Runtime Probe",
      "",
      "WPS global: " + result.hasWpsGlobal,
      "Active document: " + result.hasActiveDocument,
      "Selection available: " + result.hasSelection,
      "Document name: " + (result.documentName || "N/A"),
      "Paragraph count: " + result.paragraphCount,
      "Heading count: " + result.headingCount,
      "Adapter reachable: " + result.adapterReachable,
      "Adapter detail: " + result.adapterDetail
    ].join("\n");
  }

  function runProbe() {
    var activeDocument = getActiveDocument();
    var paragraphInfo = collectParagraphs(activeDocument);
    var result = {
      hasWpsGlobal: typeof window.wps !== "undefined",
      hasActiveDocument: !!activeDocument,
      hasSelection: !!(activeDocument && activeDocument.Selection),
      documentName: activeDocument && activeDocument.Name,
      paragraphCount: paragraphInfo.paragraphCount,
      headingCount: paragraphInfo.headingCount,
      adapterReachable: "checking",
      adapterDetail: "probing 127.0.0.1:18100/health"
    };

    var outputNode = window.document.getElementById("probe-output");
    outputNode.textContent = formatLines(result);

    fetch("http://127.0.0.1:18100/health")
      .then(function (response) {
        if (!response.ok) {
          throw new Error("HTTP " + response.status);
        }
        return response.json();
      })
      .then(function (body) {
        result.adapterReachable = true;
        result.adapterDetail = (body.data && body.data.service ? body.data.service : "unknown") +
          " / " +
          (body.data && body.data.status ? body.data.status : "unknown");
        outputNode.textContent = formatLines(result);
      })
      .catch(function (error) {
        result.adapterReachable = false;
        result.adapterDetail = error.message;
        outputNode.textContent = formatLines(result);
      });
  }

  window.openTaskpane = function () {
    return true;
  };

  var button = document.getElementById("run-probe");
  if (button) {
    button.addEventListener("click", runProbe);
  }
})();

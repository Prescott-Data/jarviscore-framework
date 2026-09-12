(function () {
  var rendering = false;

  function themeName() {
    return document.body.getAttribute("data-md-color-scheme") === "slate";
  }

  function themeVariables(dark) {
    return dark
      ? {
          primaryColor: "#172554",
          primaryTextColor: "#f8fafc",
          primaryBorderColor: "#35b0fe",
          secondaryColor: "#164e63",
          tertiaryColor: "#171923",
          lineColor: "#94a3b8",
          clusterBkg: "#12141a",
          clusterBorder: "#3f4658",
          edgeLabelBackground: "#16181f",
          actorBkg: "#172554",
          actorBorder: "#35b0fe",
          actorTextColor: "#f8fafc",
          signalColor: "#94a3b8",
          signalTextColor: "#f8fafc",
          noteBkgColor: "#164e63",
          noteBorderColor: "#22d3ee",
          noteTextColor: "#f8fafc",
        }
      : {
          primaryColor: "#eef3ff",
          primaryTextColor: "#172033",
          primaryBorderColor: "#1758f5",
          secondaryColor: "#ecfeff",
          tertiaryColor: "#f8fafc",
          lineColor: "#64748b",
          clusterBkg: "#f8fafc",
          clusterBorder: "#cbd5e1",
          edgeLabelBackground: "#ffffff",
          actorBkg: "#eef3ff",
          actorBorder: "#1758f5",
          actorTextColor: "#172033",
          signalColor: "#475569",
          signalTextColor: "#172033",
          noteBkgColor: "#ecfeff",
          noteBorderColor: "#0891b2",
          noteTextColor: "#172033",
        };
  }

  async function renderDiagrams(reset) {
    if (!window.mermaid || rendering) return;

    var diagrams = [];
    document.querySelectorAll("pre.mermaid-source").forEach(function (source) {
      var diagram = document.createElement("div");
      diagram.className = "mermaid";
      diagram.dataset.mermaidSource = source.textContent || "";
      diagram.textContent = diagram.dataset.mermaidSource;
      source.replaceWith(diagram);
      diagrams.push(diagram);
    });

    if (reset) {
      document.querySelectorAll(".mermaid[data-mermaid-source]").forEach(function (diagram) {
        diagram.removeAttribute("data-processed");
        diagram.textContent = diagram.dataset.mermaidSource || "";
        diagrams.push(diagram);
      });
    }

    if (!diagrams.length) return;

    rendering = true;
    var dark = themeName();
    window.mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      theme: "base",
      themeVariables: themeVariables(dark),
      fontFamily: "Inter, sans-serif",
    });
    try {
      await window.mermaid.run({ nodes: diagrams });
    } finally {
      rendering = false;
    }
  }

  if (typeof document$ !== "undefined") {
    document$.subscribe(function () {
      renderDiagrams(false);
    });
  } else {
    document.addEventListener("DOMContentLoaded", function () {
      renderDiagrams(false);
    });
  }

  new MutationObserver(function (mutations) {
    if (mutations.some(function (item) {
      return item.attributeName === "data-md-color-scheme";
    })) {
      renderDiagrams(true);
    }
  }).observe(document.body, { attributes: true });
})();
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from flask import Flask, jsonify, request
from flask_cors import CORS

from parse_clarts import parse_report


app = Flask(__name__)
allowed_origin = os.environ.get("CLARTS_ALLOWED_ORIGIN", "*")
CORS(app, resources={r"/api/*": {"origins": allowed_origin}})


@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "clarts-parser"})


@app.post("/api/parse-report")
def parse_uploaded_report():
    uploaded = request.files.get("pdf")
    if uploaded is None or not uploaded.filename:
        return jsonify({"error": "No PDF file was uploaded."}), 400

    filename = Path(uploaded.filename).name
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        pdf_path = temp_path / filename
        uploaded.save(pdf_path)
        report = parse_report(pdf_path, temp_path / "ocr")
    return jsonify({"report": report})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8767"))
    app.run(host="0.0.0.0", port=port)

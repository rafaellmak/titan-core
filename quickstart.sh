#!/bin/bash
export PATH="/home/ubunote/.local/bin:$PATH"
cd /teamspace/studios/this_studio/titan-core-v12

echo "=== Titan Core v12.0.0 - Quick Start ==="
echo "Workspace: $(pwd)"
echo ""

echo "1. Detectando workspace..."
titan info

echo ""
echo "2. Indexando recipes..."
titan recipe index

echo ""
echo "3. Mostrando openssl..."
titan recipe show openssl

echo ""
echo "4. Explicando openssl..."
titan explain openssl

echo ""
echo "5. Scan de segurança (stub offline)..."
titan security --stub

echo ""
echo "6. Digital Twin - criando snapshot..."
titan twin snapshot quickstart-test

echo ""
echo "7. Listando snapshots..."
titan twin snapshots

echo ""
echo "8. Telemetria..."
titan telemetry

echo ""
echo "=== Pronto para desenvolvimento! ==="
echo "Comandos: titan --help"

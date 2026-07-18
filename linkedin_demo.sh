#!/bin/bash
# LinkedIn Demo Script for Titan Core v12.0.0
# Run this and record your screen (OBS, simplescreenrecorder, etc.)

set -e

cd /home/ubunote/projects/titan-core-v12
export PATH="$HOME/.local/bin:$PATH"

echo "=========================================="
echo "  TITAN CORE v12.0.0 - LinkedIn Demo"
echo "  Embedded Intelligence Runtime for Yocto/Buildroot"
echo "=========================================="
echo ""
sleep 2

echo "1. WORKSPACE DETECTION"
echo "-------------------------"
titan info
sleep 2

echo ""
echo "2. RECIPE INDEXING"
echo "---------------------"
titan recipe index
sleep 1

echo ""
echo "3. RECIPE DETAILS"
echo "--------------------"
titan recipe show openssl
sleep 1

echo ""
echo "4. TECHNICAL EXPLANATION"
echo "---------------------------"
titan explain openssl
sleep 2

echo ""
echo "5. SECURITY SCAN (Offline Stub)"
echo "-----------------------------------"
titan security --stub
sleep 2

echo ""
echo "6. BUILD LOG DIAGNOSIS"
echo "--------------------------"
cat > /tmp/demo_build.log << 'LOG'
ERROR: Task (/home/ubunote/projects/titan-core-v12/meta-test/recipes-connectivity/openssl/openssl_3.0.bb:do_compile) failed with exit code '1'
NOTE: recipe openssl-3.0-r0: task do_compile: Started
ERROR: openssl-3.0-r0 do_compile: oe_runmake failed
ERROR: openssl-3.0-r0 do_compile: Execution of '/home/ubunote/projects/titan-core-v12/meta-test/recipes-connectivity/openssl/openssl_3.0.bb:do_compile' failed with exit code 1
ERROR: Task (/home/ubunote/projects/titan-core-v12/meta-test/recipes-example/example/example_1.0.bb:do_install) failed with exit code '1'
NOTE: recipe example-1.0-r0: task do_install: Started
ERROR: example-1.0-r0 do_install: 'install' failed
ERROR: Logfile of failure stored in: /home/ubunote/build/tmp/work/aarch64-poky-linux/example/1.0-r0/temp/log.do_install.12345
ERROR: Found 2 errors in 2 tasks
Summary: There were 2 ERROR messages shown, returning a non-zero exit code.
LOG
titan diagnose /tmp/demo_build.log
sleep 2

echo ""
echo "7. AUTO-FIX ENGINE"
echo "---------------------"
titan fix /tmp/demo_build.log
sleep 2

echo ""
echo "8. DIGITAL TWIN - SNAPSHOT"
echo "------------------------------"
titan twin snapshot linkedin-demo-$(date +%s)
sleep 1

echo ""
echo "9. DIGITAL TWIN - LIST SNAPSHOTS"
echo "------------------------------------"
titan twin snapshots
sleep 1

echo ""
echo "10. HARDWARE ANALYSIS (DTS)"
echo "------------------------------"
cat > /tmp/demo.dts << 'DTS'
/dts-v1/;
/ {
    model = "Demo Board";
    compatible = "vendor,demo-board";
    #address-cells = <1>;
    #size-cells = <1>;
    
    cpus {
        #address-cells = <1>;
        #size-cells = <0>;
        cpu@0 {
            device_type = "cpu";
            compatible = "arm,cortex-a53";
            reg = <0>;
        };
    };
    
    memory@40000000 {
        device_type = "memory";
        reg = <0x40000000 0x40000000>;
    };
};
DTS
titan hardware /tmp/demo.dts
sleep 2

echo ""
echo "11. LLM ASSISTANT (Offline Mock)"
echo "------------------------------------"
titan llm-assist --provider offline "como corrigir erro de compilacao do openssl" -y
sleep 2

echo ""
echo "12. TELEMETRY"
echo "-----------------"
titan telemetry
sleep 1

echo ""
echo "=========================================="
echo "  DEMO COMPLETO - Titan Core v12.0.0"
echo "  GitHub: https://github.com/rafaellmak/titan-core"
echo "=========================================="
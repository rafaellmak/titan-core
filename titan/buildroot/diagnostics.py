COMMON_ERRORS = {
    'external toolchain not found': {
        'category': 'toolchain',
        'solution': 'Verify BR2_TOOLCHAIN_EXTERNAL_PATH'
    },
    'fakeroot failed': {
        'category': 'rootfs',
        'solution': 'Install fakeroot package'
    },
    'wget failed': {
        'category': 'download',
        'solution': 'Check internet access and mirrors'
    },
    'patch failed': {
        'category': 'patch',
        'solution': 'Verify package version and patch compatibility'
    },
    'gcc internal compiler error': {
        'category': 'compiler',
        'solution': 'Verify host compiler and available memory'
    },
    'cannot find -l': {
        'category': 'linker',
        'solution': 'Check if necessary libraries are enabled in Buildroot config'
    },
    'No rule to make target': {
        'category': 'make',
        'solution': 'Verify the build target exists in the Buildroot tree'
    },
    'No space left on device': {
        'category': 'storage',
        'solution': 'Free up disk space or increase available storage'
    },
    'configure: error:': {
        'category': 'configure',
        'solution': 'Check if all build dependencies for this package are met'
    },
    'undefined reference': {
        'category': 'linker',
        'solution': 'Missing library or symbol. Check package dependencies.'
    },
}


def analyze_build_log(log_text):
    findings = []
    text = log_text.lower()

    for error, info in COMMON_ERRORS.items():
        if error.lower() in text:
            findings.append({
                'error': error,
                'category': info['category'],
                'solution': info['solution']
            })

    return findings
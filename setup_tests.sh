#!/bin/bash
# Setup script for KiCad Library Testing System

echo "Setting up KiCad Library Testing System..."
echo "=========================================="

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required but not installed."
    exit 1
fi

echo "✅ Python 3 found: $(python3 --version)"

# Install Python dependencies
echo ""
echo "Installing Python dependencies..."
if [ -f "requirements.txt" ]; then
    python3 -m pip install -r requirements.txt
    echo "✅ Dependencies installed"
else
    echo "❌ requirements.txt not found"
    exit 1
fi

# Create tests directory if it doesn't exist
if [ ! -d "tests" ]; then
    mkdir tests
    echo "✅ Created tests directory"
fi

# Check if test configuration exists
if [ ! -f "tests/test_config.yaml" ]; then
    echo "❌ Test configuration file missing: tests/test_config.yaml"
    echo "   This should have been created by the setup process."
    exit 1
fi

echo "✅ Test configuration found"

# Run a quick validation test
echo ""
echo "Running validation test..."
if python3 component_validator.py --quiet; then
    echo "✅ Initial validation passed"
else
    echo "⚠️  Validation found issues (this is normal for initial setup)"
    echo "   Run 'python component_validator.py' for details"
fi

echo ""
echo "🎉 Setup complete!"
echo ""
echo "Usage:"
echo "  python component_validator.py          # Standalone validation"  
echo "  python -m pytest tests/ -v            # Pytest with detailed output"
echo "  python main.py                        # Full library generation with validation"
echo ""
echo "Configuration:"
echo "  Edit tests/test_config.yaml to customize validation rules"
echo ""
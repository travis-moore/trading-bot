# VS Code Debug Configuration Setup Guide

## Quick Setup

### 1. Create .vscode Directory
```bash
mkdir -p .vscode
```

### 2. Copy Configuration Files

**Option A: Standard Configuration** (simpler, recommended)
```bash
cp launch.json .vscode/launch.json
```

**Option B: Enhanced Configuration** (more features)
```bash
cp launch_enhanced.json .vscode/launch.json
```

**Settings File** (optional but recommended)
```bash
cp settings.json .vscode/settings.json
```

### 3. Your Project Structure Should Look Like This
```
your-project/
├── .vscode/
│   ├── launch.json       # Debug configurations
│   └── settings.json     # VS Code settings (optional)
├── test_trading_api.py   # Your test suite
└── your_api_module.py    # Your actual trading API code
```

## Available Debug Configurations

### 🚀 Main Configurations

| Name | Description | Use Case |
|------|-------------|----------|
| **Run All Tests (Automated)** | Runs entire test suite | Quick validation of all functions |
| **Interactive Test Mode** | Menu-driven testing | Testing individual functions with custom inputs |

### 🐛 Category-Specific Debugging

| Name | Description |
|------|-------------|
| **Debug: Stock Price Tests** | Only stock price functions |
| **Debug: Market Depth Tests** | Only market depth subscriptions |
| **Debug: Options Tests** | Only options chain functions |
| **Debug: Order Management Tests** | Only order placement/cancellation |
| **Debug: Account Tests** | Only account balance/positions |
| **Debug: Streaming Tests** | Only quote streaming functions |

### 🔍 Advanced Debugging

| Name | Description | Use Case |
|------|-------------|----------|
| **Debug with Breakpoints** | Full step-through debugging | Finding bugs in specific code paths |
| **Debug Current File** | Debug whatever file is open | Quick ad-hoc debugging |
| **Debug with External API** | Connect to real trading API | Testing with live data |

### 🧪 Specialized Debugging

| Name | Description |
|------|-------------|
| **Debug Failed Tests Only** | Re-run only tests that failed last time |
| **Debug Single Test Function** | Pick one specific test to debug |
| **Debug with Verbose Output** | Extra detailed logging |

## How to Use

### Method 1: Debug Panel (Recommended)
1. Open VS Code
2. Press `Ctrl+Shift+D` (Windows/Linux) or `Cmd+Shift+D` (Mac)
3. Select a configuration from the dropdown at the top
4. Press `F5` or click the green play button

### Method 2: Command Palette
1. Press `Ctrl+Shift+P` (Windows/Linux) or `Cmd+Shift+P` (Mac)
2. Type "Debug: Select and Start Debugging"
3. Choose your configuration

### Method 3: Keyboard Shortcuts
- `F5` - Start debugging with currently selected configuration
- `Ctrl+F5` - Run without debugging
- `F9` - Toggle breakpoint on current line
- `F10` - Step over
- `F11` - Step into
- `Shift+F11` - Step out
- `Shift+F5` - Stop debugging

## Setting Breakpoints

### In Your Test File
1. Open `test_trading_api.py`
2. Click in the left margin next to the line number where you want to pause
3. A red dot appears = breakpoint is set
4. Start debugging - execution will pause at this line

### Recommended Breakpoint Locations
```python
# In test methods - to see what's being tested
def test_get_stock_price_basic(self):
    result = get_stock_price("AAPL")  # ← Set breakpoint here
    assert "symbol" in result

# In API functions - to debug your implementation
def get_stock_price(symbol: str):
    # Your actual API code
    response = api.call()  # ← Set breakpoint here
    return response
```

## Debug Console Commands

While debugging, you can use the Debug Console to inspect variables:

```python
# Print variable value
result

# Evaluate expression
result["price"] * 100

# Call function
get_stock_price("GOOGL")

# Check type
type(result)
```

## Common Debugging Workflows

### Workflow 1: Debug a Failing Test
1. Run all tests: Select "Run All Tests (Automated)"
2. Note which test fails
3. Select "Debug Single Test Function"
4. Choose the failed test from the dropdown
5. Set breakpoints in the test and/or your API function
6. Step through to find the issue

### Workflow 2: Debug New Function
1. Write your new API function
2. Write a test for it
3. Set breakpoints in both test and function
4. Select "Debug with Breakpoints"
5. Press `F5`
6. Use `F10` (step over) and `F11` (step into) to trace execution

### Workflow 3: Interactive Testing with Debugging
1. Select "Interactive Test Mode"
2. Press `F5`
3. When you select a test from the menu, you can set breakpoints
4. Step through to see exactly what's happening

## Tips & Tricks

### 1. Conditional Breakpoints
Right-click on a breakpoint → "Edit Breakpoint" → Add condition
```python
# Only pause when symbol is "AAPL"
symbol == "AAPL"

# Only pause on iteration 5
i == 5
```

### 2. Logpoints
Right-click in margin → "Add Logpoint"
```python
Price is {result['price']}
```
Logs to Debug Console without stopping execution

### 3. Watch Expressions
In Debug panel, add expressions to "Watch" section:
- `result["price"]`
- `len(positions)`
- `order_status`

### 4. Debug Environment Variables
Edit launch.json to add environment variables:
```json
"env": {
    "API_KEY": "your-key-here",
    "DEBUG": "1",
    "LOG_LEVEL": "DEBUG"
}
```

## Troubleshooting

### Problem: "Python interpreter not found"
**Solution:** 
```json
// In settings.json, update:
"python.defaultInterpreterPath": "/path/to/your/python"
```

### Problem: Breakpoints not working
**Solution:** 
- Make sure `"justMyCode": false` in launch.json
- Ensure you're debugging (F5) not just running (Ctrl+F5)

### Problem: Variables not showing in Debug panel
**Solution:** 
- Set `"debug.inlineValues": true` in settings.json
- Use Watch panel to manually add variables

### Problem: Tests not found with pytest
**Solution:**
- Install pytest: `pip install pytest`
- Or use the basic configuration without pytest

## Next Steps

1. ✅ Set up the .vscode directory
2. ✅ Copy launch.json and settings.json
3. ✅ Open test_trading_api.py
4. ✅ Set a breakpoint in a test method
5. ✅ Press F5 and start debugging!

## Example Debug Session

```
1. Open test_trading_api.py
2. Go to line with: result = get_stock_price("AAPL")
3. Click in margin to set breakpoint (red dot appears)
4. Press Ctrl+Shift+D to open Debug panel
5. Select "Debug with Breakpoints" from dropdown
6. Press F5
7. Execution pauses at your breakpoint
8. Hover over variables to see their values
9. Press F10 to step to next line
10. Press F11 to step into get_stock_price() function
11. Use Debug Console to inspect: print(result)
12. Press F5 to continue to next breakpoint
```

Happy debugging! 🐛🔍

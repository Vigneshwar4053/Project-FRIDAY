"""Optional developer CLI, preserving legacy switches and diagnostics."""
import runpy

def main():
    runpy.run_module('friday.main', run_name='__main__')

if __name__ == '__main__':
    main()

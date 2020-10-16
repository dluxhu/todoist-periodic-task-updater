from setuptools import setup

setup(
    name='ToroistPeriodicTaskUpdater',
    version='0.1',
    py_modules=['todoist-periodic-task-updater'],
    url='https://github.com/dluxhu/todoist-periodic-task-updater',
    license='MIT',
    author='Balazs Szabo',
    author_email='1@dlux.cc',
    description='Updates Todoist tasks based on various rules.',
    entry_points={
        "console_scripts": [
            "todoist-periodic-task-updater=todoist-periodic-task-updater:main",
        ],
    },
    install_requires=[
        'todoist-python',
    ]
)

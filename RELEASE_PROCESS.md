* double-check the version number in `saga_tools/version.py` matches the desired release version
* run `towncrier` and commit the updated changelog
* be sure `dist` is empty
* `python setup.py sdist bdist_wheel`
* `twine upload dist/*`
* bump version number in `saga_tools/version.py`

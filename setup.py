from setuptools import setup, find_packages

setup(
    name='bee-rpc-over-grpc',
    version='0.0.0',

    url='https://github.com/bee-rpc-protocol/bee-rpc-over-grpc-py.git',

    py_modules=[
        'bee_rpc'
    ],
    install_requires=[
        'grpcio==1.56.0',
        'protobuf==4.23.3',
    ],
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    python_requires=">=3.11",
)

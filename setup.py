#!/usr/bin/env python
# -*- mode: python; coding: utf-8 -*-

# Copyright (C) 2020, Chumba <concretekahuna@protonmail.com>
# This software is under the terms of Apache License v2 or later.


try:
    from setuptools import setup, find_packages
except ImportError:
    from distutils.core import setup 

setup(
    name='anovamqtt',
    author='Chumba',
    author_email='concretekahuna@protonmail.com',
    version='0.0.2',
    packages=find_packages(),
    url='https://github.com/Chumba/anovamqtt',
    license='Apache License 2.0',
    install_requires=[
        'pygatt',
        'retry',
        'paho-mqtt'
    ],
    description='A Python Library for Anova Nano Precision Cooker',
    long_description_content_type="text/markdown",
    long_description=open('README.md').read(),
    zip_safe=False,
    include_package_data=True,
    classifiers=(
        'Intended Audience :: Developers',
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7'
    )
)

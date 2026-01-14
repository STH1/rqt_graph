from setuptools import setup

package_name = 'rqt_graph_focus'
setup(
    name=package_name,
    version='1.0.0',
    package_dir={'': 'src'},
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name + '/resource', ['resource/RosGraph.ui']),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name, ['plugin.xml']),
        ('lib/' + package_name, ['scripts/rqt_graph_focus']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    author='STH1',
    maintainer='STH1',
    maintainer_email='',
    keywords=['ROS'],
    classifiers=[
        'Intended Audience :: Developers',
        'Programming Language :: Python',
        'Topic :: Software Development',
    ],
    description=(
        'rqt_graph_focus - rqt_graph fork with click-to-focus and connection list.'
    ),
    license='BSD',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'rqt_graph_focus = rqt_graph_focus.main:main',
        ],
    },
)

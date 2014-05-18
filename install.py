# installer for IDOKEP
# Copyright 2014 Lorant Kurthy

from setup import ExtensionInstaller

def loader():
    return IDOKEPInstaller()

class IDOKEPInstaller(ExtensionInstaller):
    def __init__(self):
        super(IDOKEPInstaller, self).__init__(
            version="0.1",
            name='idokep',
            description='Upload weather data to www.idokep.hu.',
            author="Lorant Kurthy",
            author_email="kurthyl@gmail.com",
            restful_services='user.idokep.IDOKEP',
            config={
                'StdRESTful': {
                    'IDOKEP': {
                        'username': 'INSERT_USERNAME_HERE',
                        'password': 'INSERT_PASSWORD_HERE'}}},
            files=[('bin/user', ['bin/user/idokep.py'])]
            )

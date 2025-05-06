# Senior-Project
Repo for Senior Project Course

<<<<<<< HEAD
<<<<<<< HEAD
commit testing
=======
I sent a secret.env file to you on discord. Put it in the same directory as the manage.py file.
=======
In order to run this you will need to do the following:
>>>>>>> 3605a7a9d0e5625312d453d9b3aa6c4db220e431

    - Go to https://developer.spotify.com/dashboard and create an account
        - click create new app
        - You can name it and add a description as you like, put 'http://127.0.0.1:8000/' as the redirect URI
        - Once you have created a new app, find your Client ID and Client secret, as we will be using them later
    - Navigate to the folder where your manage.py file is, 
    - Create a new file named 'secret.csv' 
    - in the secret.csv file you will put this:

    SPOTIPY_CLIENT_ID=YOUR_CLIENT_ID
    SPOTIPY_CLIENT_SECRET=YOUR_CLIENT_SECRET
    SPOTIPY_REDIRECT_URI=http://http://127.0.0.1:8000/

    - Make sure you have python installed
    - In your terminal, type:

    pip install django
    pip install spotipy

    - once you have done that, type the following:

    python manage.py makemigrations
    python manage.py migrate

     - After that is complete, to run the server use this command:

    python manage.py runserver

    - In your browser go to: http://127.0.0.1:8000/ 

<<<<<<< HEAD
Then go to your localhost or http://127.0.0.1:8000/ in your browser
>>>>>>> 6aa791be70844e2a1724f20d712b5e66a07eefc3
=======
>>>>>>> 3605a7a9d0e5625312d453d9b3aa6c4db220e431

# Senior-Project
Repo for Senior Project Course

In order to run this you will need to do the following:

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


"""REST API for calculating rigor."""
import string
import os
import subprocess
import urllib
import shutil
from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
import werkzeug.exceptions
from google.cloud import vision
import PyPDF2

if not os.path.isdir('./submissions'):
    os.mkdir('./submissions')

app = Flask(__name__) # pylint: disable=invalid-name
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024

@app.after_request
def apply_headers(response):
    """Add headers to every response."""
    origin = request.environ.get('HTTP_ORIGIN', '')
    host = urllib.parse.urlparse(origin).hostname
    if host in ('localhost', '127.0.0.1'):
        response.headers['Access-Control-Allow-Origin'] = origin
    response.headers['Access-Control-Allow-Methods'] = 'POST, GET, OPTIONS, PUT'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Vary'] = 'Origin'
    return response

@app.errorhandler(werkzeug.exceptions.RequestEntityTooLarge)
def handle_too_large(error):
    """Handle error when request is too large."""
    response = jsonify({'error': 'Upload too large.'})
    response.status_code = error.status_code
    return response

@app.route('/text', methods=('POST',))
def text_rigor():
    """Return the rigor of text."""
    return jsonify({'result': str_rigor(request.json['text'])})

@app.route('/pdf', methods=('POST',))
def pdf_rigor():
    """Return the rigor of a PDF."""
    file = request.files.get('file')
    if not file or not file.filename or not file.filename.endswith('.pdf'):
        return jsonify({'error': 'Invalid file.'})

    filename = secure_filename(file.filename)
    filepath = os.path.join('./submissions', filename)
    file.save(filepath)
    subprocess.call(['gs', '-sDEVICE=txtwrite', '-dFILTERIMAGE', '-o', 'output.txt', filepath])
    os.remove(filepath)

    pdf = PyPDF2.PdfFileReader(filepath)
    num_pages = pdf.getNumPages()

    with open('output.txt', 'r') as text_file:
        text = text_file.read()
        is_probably_scanned = len(text.split()) / num_pages < 20

    if not is_probably_scanned:
        return jsonify({'result': str_rigor(text)})

    return jsonify(
        {'error': 'This looks like a scanned PDF. Please submit a text PDF.'}
    )


@app.route('/image', methods=('POST',))
def image_rigor():
    """Return the rigor of an image."""
    file = request.files.get('file')
    if not file or not file.filename or not file.filename.endswith(
            ('.jpeg', '.jpg', '.png', '.gif', '.bmp', '.tiff')
    ):
        return jsonify({'error': 'Not an accepted file format.'})

    filename = secure_filename(file.filename)
    filepath = os.path.join('./submissions', filename)
    file.save(filepath)

    text = img_to_text(filepath)
    os.remove(filepath)
    return jsonify({'result': str_rigor(text)})

@app.route('/url', methods=('POST',))
def url_rigor():
    """Return the rigor of a PDF or image URL."""
    url = request.json['url']

    # Check that URL is pdf or image
    if not url.endswith(
            ('.jpeg', '.jpg', '.png', '.gif', '.bmp', '.tiff', '.pdf')
    ):
        return jsonify({'error': 'Not an accepted file format.'})

    try:
        resp = urllib.request.urlopen(url)
    except urllib.error.URLError:
        return jsonify({'error': 'Invalid URL.'})

    # Download file
    parsed_url = urllib.parse.urlparse(url)
    filename = os.path.basename(parsed_url.path)
    filepath = os.path.join('./submissions', filename)
    with open(filepath, 'wb') as out_file:
        shutil.copyfileobj(resp, out_file) # TODO: limit file size

    if filename.endswith('.pdf'):
        # Determine if PDF is text or image
        subprocess.call(['gs', '-sDEVICE=txtwrite', '-dFILTERIMAGE', '-o', 'output.txt', filepath])
        os.remove(filepath)

        pdf = PyPDF2.PdfFileReader(filepath)
        num_pages = pdf.getNumPages()

        with open('output.txt', 'r') as text_file:
            text = text_file.read()
            is_probably_scanned = len(text.split()) / num_pages < 20

        if not is_probably_scanned:
            return jsonify({'result': str_rigor(text)})

        return jsonify(
            {'error': 'This looks like a scanned PDF. Please submit a text PDF.'}
        )

    text = img_to_text(filepath)
    os.remove(filepath)
    return jsonify({'result': str_rigor(text)})

def generate_rigor_tree(rules: dict):
    """Generate a state tree from rigor rules"""

def calculate_rigor(wordlist: list):
    """Calculate the rigor of a list of words."""
    root_state = {
        'oper': lambda cur: cur,
        'next': {
            'assume': {
                'oper': lambda cur: cur + 0.3,
                'next': {}
            },
            'suppose': {
                'oper': lambda cur: cur + 0.3,
                'next': {}
            },
            'hence': {
                'oper': lambda cur: cur + 1,
                'next': {}
            },
            'since': {
                'oper': lambda cur: cur + 1,
                'next': {}
            },
            'then': {
                'oper': lambda cur: cur + 1,
                'next': {}
            },
            'therefore': {
                'oper': lambda cur: cur + 1,
                'next': {}
            },
            'thus': {
                'oper': lambda cur: cur + 1,
                'next': {}
            },
            'it': {
                'oper': lambda cur: cur,
                'next': {
                    'follows': {
                        'oper': lambda cur: cur + 1,
                        'next': {}
                    }
                }
            },
            'without': {
                'oper': lambda cur: cur,
                'next': {
                    'loss': {
                        'oper': lambda cur: cur,
                        'next': {
                            'of': {
                                'oper': lambda cur: cur,
                                'next': {
                                    'generality': {
                                        'oper': lambda cur: cur**1.05,
                                        'next': {}
                                    }
                                }
                            }
                        }
                    }
                }
            },
            'wlog': {
                'oper': lambda cur: cur**1.05,
                'next': {}
            },
            'by': {
                'oper': lambda cur: cur,
                'next': {
                    'definition': {
                        'oper': lambda cur: cur + 2,
                        'next': {}
                    },
                    'hypothesis': {
                        'oper': lambda cur: cur + 3,
                        'next': {}
                    },
                    'the': {
                        'oper': lambda cur: cur,
                        'next': {
                            'inductive': {
                                'oper': lambda cur: cur,
                                'next': {
                                    'hypothesis': {
                                        'oper': lambda cur: cur * 1.5,
                                        'next': {}
                                    }
                                }
                            },
                            'induction': {
                                'oper': lambda cur: cur,
                                'next': {
                                    'hypothesis': {
                                        'oper': lambda cur: cur * 1.5,
                                        'next': {}
                                    }
                                }
                            }
                        }
                    },
                    'inductive': {
                        'oper': lambda cur: cur,
                        'next': {
                            'hypothesis': {
                                'oper': lambda cur: cur * 1.5,
                                'next': {}
                            }
                        }
                    },
                    'induction': {
                        'oper': lambda cur: cur,
                        'next': {
                            'hypothesis': {
                                'oper': lambda cur: cur * 1.5,
                                'next': {}
                            }
                        }
                    },
                    'symmetry': {
                        'oper': lambda cur: cur + 30,
                        'next': {}
                    }
                }
            },
            'case': {
                'oper': lambda cur: cur + 1,
                'next': {}
            },
            'claim': {
                'oper': lambda cur: cur + 5,
                'next': {}
            },
            'lemma': {
                'oper': lambda cur: cur + 10,
                'next': {}
            },
            'clearly': {
                'oper': lambda cur: cur - 11,
                'next': {}
            },
            'obviously': {
                'oper': lambda cur: cur - 22,
                'next': {}
            },
            'trivial': {
                'oper': lambda cur: cur - 33,
                'next': {}
            },
            'of': {
                'oper': lambda cur: cur,
                'next': {
                    'course': {
                        'oper': lambda cur: cur - 33,
                        'next': {}
                    }
                }
            },
            'in': {
                'oper': lambda cur: cur,
                'next': {
                    'particular': {
                        'oper': lambda cur: cur * 1.1,
                        'next': {}
                    }
                }
            },
            'qed': {
                'oper': lambda cur: cur + 50,
                'next': {}
            },
            'where': {
                'oper': lambda cur: cur - 0.5,
                'next': {}
            }
        }
    }
    state = root_state
    score = 100
    for word in wordlist:
        word = word.lower()
        state = state['next'].get(word)

        if not state:
            state = root_state['next'].get(word)

        if not state:
            state = root_state

        score = state['oper'](score)

    return score

def str_rigor(text: str):
    """Get the rigor of a string."""
    return calculate_rigor(text.translate(
        str.maketrans(string.punctuation, len(string.punctuation) * ' ')
    ).split())

def img_to_text(path: str):
    """Convert an image to text."""
    client = vision.ImageAnnotatorClient()
    filename = os.path.abspath(path)

    with open(filename, 'rb') as image_file:
        content = image_file.read()

    image = vision.types.Image(content=content) # pylint: disable=no-member
    response = client.document_text_detection(image) # pylint: disable=no-member

    return response.full_text_annotation.text

    for page in response.full_text_annotation.pages:
        for block in page.blocks:
            print('\nBlock confidence: {}\n'.format(block.confidence))

            for paragraph in block.paragraphs:
                print('Paragraph confidence: {}'.format(
                    paragraph.confidence))

                for word in paragraph.words:
                    word_text = ''.join([
                        symbol.text for symbol in word.symbols
                    ])
                    print('Word text: {} (confidence: {})'.format(
                        word_text, word.confidence))

                    for symbol in word.symbols:
                        print('\tSymbol: {} (confidence: {})'.format(
                            symbol.text, symbol.confidence))

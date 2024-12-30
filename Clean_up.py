import shutil
import os , sys
DICO = {}
FILES = ["/IMAGES","/PDFS","/VIDEOS","/ZIPS","/HTML","/OTHERS","/SCRIPTS"]
EXT=[["jpeg","jpg","png"],["pdf"],["mp3","mp4"],["zip"],["html"],[],["py","js","c","java"]]
def exists(f):
    for i in FILES:
        if(i=="/"+f):
            return True
    return False
def recherche_cle(ext):
    for k in DICO.keys():
        for n in DICO[k]:
            if(n==ext):
                return k
    return None
def init_dico():
    for i in range(len(FILES)):
        f = FILES[i]
        DICO[f] = EXT[i]
    print(f"!!! Dico initialiser !!!\n")
    
def verif_init_dossiers(extension=[]):
    init_dico()
    if(len(extension) >0):
        for ext in extension:
            f = recherche_cle(ext)
            if(not os.path.exists(f)):
                try:
                    os.mkdir(f.split("/")[-1])
                except FileExistsError or ValueError:
                    print(f"!!! {extension} existe déja \n")
                    exit
    else:
        for f in FILES:
            if(not os.path.exists(f)):
                if(len(FILES) != len(EXT)):
                    print("!!! Erreur : Pas assez d'extensions pour les differents types de fichiers !!! \n")
                    exit
                try:
                    os.mkdir(f.split("/")[-1])
                except FileExistsError or ValueError:
                    print(f"!!! {f} existe déja \n")
                    exit 
    print(f"Verification du setup valide \n")

def file_extension(file):
    return file.split('/')[-1].split('.')[-1]
        
def TrieParExtension(CURRENT_WORKDIR,extension =[],setup=True):
    if(setup):
        verif_init_dossiers(extension)
    ALL_FILES = [f for f in os.listdir(CURRENT_WORKDIR)]
    for f in ALL_FILES :
        if(os.path.isfile(os.path.join(CURRENT_WORKDIR, f))):
            if(len(extension)>0):
                for ext in extension:
                    if(file_extension(f)==ext):
                        destination = recherche_cle(ext)
                        if(destination != None):
                            shutil.move(f,str(CURRENT_WORKDIR+destination))
                            print(f"{f} a correctement été deplacé dans {CURRENT_WORKDIR+destination} !!! \n")
                        else :
                            print(f"!!! Le deplacement de {f} n'a pas été effectué faute de clé !!!\n")
            else:
                ext = file_extension(f)
                destination = recherche_cle(ext)
                if(destination != None):
                    shutil.move(f,str(CURRENT_WORKDIR+destination))
                    print(f"{f} a correctement été deplacé dans {CURRENT_WORKDIR+destination} !!! \n")
                else :
                    print(f"!!! Le deplacement de {f} n'a pas été effectué faute de clé !!!\n")
        else :
            if(not exists(f)):
                shutil.move(f,str(CURRENT_WORKDIR+"/DOSSIERS"))
                print(f"{f} a correctement été deplacé dans {CURRENT_WORKDIR}/DOSSIERS !!!")
    

def clean_up():
    args = sys.argv 
    CURRENT_WORKDIR = os.getcwd()
    print("!!! Vous avez executer le script de trie de dossier !!!")
    print(f"\t Vous êtes dans le repertoire suivant : {CURRENT_WORKDIR} ")
    res = str(input("Êtes vous sur de vouloir poursuivre cette operation ? Y/N "))
    
    if(res=="Y"):
        Test = CURRENT_WORKDIR.split('/')
        current_simple = Test[len(Test)-1]
        
        if (current_simple!=args[1] ) :
            print(f"!!! {current_simple } :::  Vous n'êtes pas dans {args[1]} !!!")
            return 0
        else:
            if(len(args)>=2):
                ext = args[2:]
                print("on est dedans ")
                TrieParExtension(CURRENT_WORKDIR,ext)
            else:
                print("on est dedans ")
                TrieParExtension(CURRENT_WORKDIR)                
    print("\n!!! CLEAN TERMINE !!!\n")
    return 0

        
clean_up()
    # if(CURRENT_WORKDIR !="")

#include<stdio.h>

#include<string.h>

int main()

{

    char ch[101];

    int j;



    scanf("%s",&ch);

    j=strlen(ch);





    printf("%c%d%c",ch[0],j-2,ch[j-1]);

    return 0;





}
